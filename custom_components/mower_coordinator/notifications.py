"""Operator notifications for the mower coordinator.

Delivery is best-effort and failure-isolated: a slow or broken destination never
blocks other destinations or the caller, and ``async_send`` never raises (task
cancellation excepted). Protective commands must be issued before, and never wait
on, a notification; ``send_nowait`` exists for that.

Diagnostics name destinations by position (``target_1``, ``legacy_1``) and record
error codes, never exception text, because notify entity IDs and provider errors
can contain personal names, tokens or URLs.

The module deliberately avoids importing Home Assistant so its logic can be tested
offline; it only uses ``hass.services``, ``hass.config.time_zone`` and, when
present, ``hass.async_create_background_task``.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
from collections import OrderedDict, deque
from collections.abc import Callable, Mapping
from datetime import datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

EVENT_ATTENTION = 'attention'
EVENT_COMPLETE = 'complete'
EVENTS = (EVENT_ATTENTION, EVENT_COMPLETE, 'charging', 'resumed', 'started', 'hold')

DEFAULT_CONFIG: dict[str, Any] = {
    'targets': [],
    'legacy_actions': [],
    'events': [EVENT_ATTENTION, EVENT_COMPLETE],
    'quiet_start': '22:00:00',
    'quiet_end': '08:00:00',
    'urgent_override': False,
}

MAX_DESTINATIONS = 10
MAX_MESSAGE_LENGTH = 1000
SEND_TIMEOUT_SECONDS = 10.0
DEDUP_WINDOW_SECONDS = 900.0
MAX_DEDUP_KEYS = 64
RATE_LIMIT_COUNT = 20
RATE_LIMIT_WINDOW_SECONDS = 3600.0

TITLE = 'Mower coordinator'
TEST_TITLE = 'Mower coordinator: TEST notification'
TEST_PREFIX = 'TEST ONLY - not a mower event. '

_ENTITY_ID = re.compile(r'^notify\.[a-z0-9_]+$')
_SERVICE_NAME = re.compile(r'^[a-z0-9_]+$')
# notify.send_message is the entity action; persistent_notification is created separately.
_RESERVED_LEGACY = {'send_message', 'persistent_notification', 'notify'}
_TIME = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?$')


def _parse_time(value: Any) -> time | None:
    if isinstance(value, time):
        return value.replace(tzinfo=None, microsecond=0)
    if not isinstance(value, str):
        return None
    match = _TIME.fullmatch(value.strip())
    if not match:
        return None
    return time(int(match[1]), int(match[2]), int(match[3] or 0))


def _string_list(value: Any) -> list[str] | None:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) for item in value):
        return None
    result: list[str] = []
    for item in value:
        item = item.strip()
        if item and item not in result:
            result.append(item)
    return result


def validate_config(raw: Mapping[str, Any] | None) -> tuple[dict[str, Any], dict[str, str]]:
    """Normalize notification options. Returns ``(config, errors)``.

    ``errors`` maps option keys to stable error codes suitable for a config/options
    flow; it never echoes user input. ``config`` is only meaningful when ``errors``
    is empty.
    """
    errors: dict[str, str] = {}
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        return dict(DEFAULT_CONFIG), {'base': 'invalid_config'}
    unknown = set(raw) - set(DEFAULT_CONFIG)
    if unknown:
        errors['base'] = 'unknown_option'
    merged = {**DEFAULT_CONFIG, **{k: v for k, v in raw.items() if k in DEFAULT_CONFIG}}

    targets = _string_list(merged['targets'])
    if targets is None or any(not _ENTITY_ID.fullmatch(t) for t in targets):
        errors['targets'] = 'invalid_notify_entity'
        targets = []

    legacy_raw = _string_list(merged['legacy_actions'])
    legacy: list[str] = []
    if legacy_raw is None:
        errors['legacy_actions'] = 'invalid_notify_action'
    else:
        for name in legacy_raw:
            service = name[len('notify.'):] if name.startswith('notify.') else name
            if not _SERVICE_NAME.fullmatch(service) or service in _RESERVED_LEGACY:
                errors['legacy_actions'] = 'invalid_notify_action'
                break
            if service not in legacy:
                legacy.append(service)

    if len(targets) + len(legacy) > MAX_DESTINATIONS:
        errors['base'] = 'too_many_destinations'

    events = _string_list(merged['events'])
    if events is None or any(e not in EVENTS for e in events):
        errors['events'] = 'invalid_event'
        events = list(DEFAULT_CONFIG['events'])

    quiet_start = _parse_time(merged['quiet_start'])
    quiet_end = _parse_time(merged['quiet_end'])
    if quiet_start is None:
        errors['quiet_start'] = 'invalid_time'
    if quiet_end is None:
        errors['quiet_end'] = 'invalid_time'

    if not isinstance(merged['urgent_override'], bool):
        errors['urgent_override'] = 'invalid_boolean'

    config = {
        'targets': targets,
        'legacy_actions': legacy,
        'events': events,
        'quiet_start': (quiet_start or _parse_time(DEFAULT_CONFIG['quiet_start'])).isoformat(),
        'quiet_end': (quiet_end or _parse_time(DEFAULT_CONFIG['quiet_end'])).isoformat(),
        'urgent_override': merged['urgent_override'] is True,
    }
    return config, errors


def in_quiet_hours(local: time, start: time, end: time) -> bool:
    """True when ``local`` falls in [start, end). Windows may cross midnight; start == end disables quiet hours."""
    local = local.replace(tzinfo=None)
    if start == end:
        return False
    if start < end:
        return start <= local < end
    return local >= start or local < end


def _clip(text: Any, limit: int = MAX_MESSAGE_LENGTH) -> str:
    text = text if isinstance(text, str) else str(text)
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 3] + '...'


def _error_code(exc: BaseException) -> str:
    # Class names only: provider exception text can embed destinations, tokens or URLs.
    if isinstance(exc, TimeoutError):
        return 'timeout'
    return f'error:{type(exc).__name__}'


class NotificationManager:
    """Sends coordinator events to configured notify destinations."""

    def __init__(
        self,
        hass: Any,
        entry_id: str,
        config: Mapping[str, Any] | None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        normalized, errors = validate_config(config)
        if errors:
            raise ValueError('invalid notification options: ' + ', '.join(f'{k}={v}' for k, v in sorted(errors.items())))
        self._hass = hass
        self._config = normalized
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._quiet_start = _parse_time(normalized['quiet_start'])
        self._quiet_end = _parse_time(normalized['quiet_end'])
        safe_entry = re.sub(r'[^a-z0-9_]', '_', str(entry_id).lower())[:64] or 'entry'
        self._persistent_id = f'mower_coordinator_{safe_entry}_attention'
        self._destinations: list[tuple[str, str, str]] = [
            (f'target_{i}', 'entity', entity) for i, entity in enumerate(normalized['targets'], 1)
        ] + [(f'legacy_{i}', 'legacy', service) for i, service in enumerate(normalized['legacy_actions'], 1)]
        self._recent: OrderedDict[str, float] = OrderedDict()
        self._sent_times: deque[float] = deque(maxlen=RATE_LIMIT_COUNT)
        self._tasks: set[asyncio.Task] = set()
        self._send_lock = asyncio.Lock()
        self._dest_status: dict[str, dict[str, Any]] = {
            label: {'status': 'never', 'last_error': None, 'last_attempt': None} for label, _, _ in self._destinations
        }
        self._dest_status['persistent'] = {'status': 'never', 'last_error': None, 'last_attempt': None}
        self._counts = {'sent': 0, 'failed': 0, 'suppressed_quiet': 0, 'suppressed_event': 0,
                        'suppressed_duplicate': 0, 'suppressed_rate': 0, 'invalid': 0}
        self._last: dict[str, Any] = {'status': 'idle', 'event': None, 'at': None, 'last_error': None}

    @property
    def config(self) -> dict[str, Any]:
        return dict(self._config)

    def _local_now(self) -> datetime:
        try:
            zone = ZoneInfo(self._hass.config.time_zone)
        except Exception:  # noqa: BLE001 - an unset or invalid zone falls back to UTC
            zone = timezone.utc
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now.astimezone(zone)

    def is_quiet(self, now: datetime | None = None) -> bool:
        local = (now or self._local_now()).timetz()
        return in_quiet_hours(local, self._quiet_start, self._quiet_end)

    def _duplicate(self, key: str, stamp: float) -> bool:
        for old_key, sent_at in list(self._recent.items()):
            if stamp - sent_at >= DEDUP_WINDOW_SECONDS:
                del self._recent[old_key]
        return key in self._recent

    def _remember(self, key: str, stamp: float) -> None:
        self._recent[key] = stamp
        self._recent.move_to_end(key)
        while len(self._recent) > MAX_DEDUP_KEYS:
            self._recent.popitem(last=False)

    def _rate_limited(self, stamp: float) -> bool:
        return len(self._sent_times) == RATE_LIMIT_COUNT and stamp - self._sent_times[0] < RATE_LIMIT_WINDOW_SECONDS

    async def _call(self, label: str, domain: str, service: str, data: dict[str, Any],
                    target: dict[str, Any] | None, stamp: str) -> bool:
        status = self._dest_status[label]
        status['last_attempt'] = stamp
        try:
            has_service = getattr(self._hass.services, 'has_service', None)
            if has_service is not None and not has_service(domain, service):
                status.update(status='missing', last_error='service_missing')
                return False
            kwargs: dict[str, Any] = {'blocking': True}
            if target:
                kwargs['target'] = target
            async with asyncio.timeout(SEND_TIMEOUT_SECONDS):
                await self._hass.services.async_call(domain, service, data, **kwargs)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - one destination must never break the others
            status.update(status='failed', last_error=_error_code(exc))
            return False
        status.update(status='ok', last_error=None)
        return True

    def _record(self, status: str, event: str | None, at: str | None, error: str | None = None, *,
                delivered: int = 0, failed: int = 0, test: bool = False) -> dict[str, Any]:
        self._last = {'status': status, 'event': event, 'at': at, 'last_error': error}
        return {**self._last, 'delivered': delivered, 'failed': failed, 'test': test}

    async def async_send(self, event: str, message: str, urgent: bool = False, test: bool = False) -> dict[str, Any]:
        """Deliver ``message`` for ``event``. Never raises; returns a sanitized result."""
        try:
            async with self._send_lock:
                return await self._send(event, message, urgent, test)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - notification bugs must not reach mower control
            self._counts['failed'] += 1
            return self._record('failed', event if event in EVENTS else None, self._safe_now_iso(), _error_code(exc))

    def _safe_now_iso(self) -> str | None:
        try:
            return self._local_now().isoformat()
        except Exception:  # noqa: BLE001
            return None

    async def _send(self, event: str, message: str, urgent: bool, test: bool) -> dict[str, Any]:
        now = self._local_now()
        at = now.isoformat()
        stamp = now.timestamp()

        key = None
        if test:
            title = TEST_TITLE
            body = _clip(TEST_PREFIX + (_clip(message, 500) or 'Notification delivery check.'))
        else:
            if event not in EVENTS:
                self._counts['invalid'] += 1
                return self._record('invalid_event', None, at, 'invalid_event')
            body = _clip(message)
            if not body:
                self._counts['invalid'] += 1
                return self._record('invalid_message', event, at, 'empty_message')
            title = TITLE + ': ' + {'attention':'attention needed', 'complete':'mowing complete', 'charging':'charging', 'resumed':'continuing saved work', 'started':'mowing started', 'hold':'waiting'}.get(event, event)
            if urgent:
                title = 'URGENT - ' + title
            key = hashlib.sha256(f'{event}\0{body}'.encode()).hexdigest()
            if self._duplicate(key, stamp):
                self._counts['suppressed_duplicate'] += 1
                return self._record('suppressed_duplicate', event, at)

        persistent_ok = None
        # Attention always reaches the HA notification panel, whatever the push choices.
        if event == EVENT_ATTENTION and not test:
            persistent_ok = await self._call(
                'persistent', 'persistent_notification', 'create',
                {'title': title, 'message': body, 'notification_id': self._persistent_id}, None, at)

        push = True
        reason = None
        if not test:
            if event not in self._config['events']:
                push, reason = False, 'suppressed_event'
            elif self.is_quiet(now) and not (urgent and self._config['urgent_override']):
                push, reason = False, 'suppressed_quiet'
            elif not urgent and self._rate_limited(stamp):
                push, reason = False, 'suppressed_rate'

        delivered = failed = 0
        if push:
            destinations = self._destinations
            if test and not destinations:
                destinations = [('persistent', 'persistent', '')]
            for label, kind, name in destinations:
                if kind == 'entity':
                    ok = await self._call(label, 'notify', 'send_message',
                                          {'title': title, 'message': body}, {'entity_id': name}, at)
                elif kind == 'legacy':
                    ok = await self._call(label, 'notify', name, {'title': title, 'message': body}, None, at)
                else:
                    ok = await self._call(label, 'persistent_notification', 'create',
                                          {'title': title, 'message': body,
                                           'notification_id': self._persistent_id + '_test'}, None, at)
                delivered += ok
                failed += not ok
            if delivered and not test:
                self._sent_times.append(stamp)
        else:
            self._counts[reason] += 1

        if persistent_ok is not None:
            delivered += persistent_ok
            failed += not persistent_ok

        # A message counts as handled once something reached the operator or quiet/event
        # choices deliberately held it; a total delivery failure stays retryable.
        if key is not None and (delivered or (not push and not failed)):
            self._remember(key, stamp)

        if failed and delivered:
            status = 'partial'
        elif failed:
            status = 'failed'
        elif not push:
            status = reason
        elif delivered:
            status = 'test_sent' if test else 'sent'
        else:
            status = 'no_destinations'
        self._counts['sent'] += delivered
        self._counts['failed'] += failed
        error = None
        if failed:
            error = next((s['last_error'] for s in self._dest_status.values()
                          if s['last_attempt'] == at and s['last_error']), 'delivery_failed')
        return self._record(status, None if test else event, at, error,
                            delivered=delivered, failed=failed, test=test)

    def send_nowait(self, event: str, message: str, urgent: bool = False) -> asyncio.Task:
        """Schedule ``async_send`` in the background so the caller (e.g. a dock command path) never waits on it."""
        coro = self.async_send(event, message, urgent)
        create = getattr(self._hass, 'async_create_background_task', None)
        if create is not None:
            task = create(coro, f'mower_coordinator_notify_{event}')
        else:
            task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def diagnostics(self) -> dict[str, Any]:
        """Sanitized state for HA diagnostics: no destination IDs, messages or exception text."""
        return {
            'status': self._last['status'],
            'last_event': self._last['event'],
            'last_attempt': self._last['at'],
            'last_error': self._last['last_error'],
            'counts': dict(self._counts),
            'destinations': {label: dict(state) for label, state in self._dest_status.items()},
            'options': {
                'target_count': len(self._config['targets']),
                'legacy_action_count': len(self._config['legacy_actions']),
                'events': list(self._config['events']),
                'quiet_start': self._config['quiet_start'],
                'quiet_end': self._config['quiet_end'],
                'urgent_override': self._config['urgent_override'],
            },
        }

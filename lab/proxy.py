"""Fixed-destination TCP forwarder for localhost lab UI; never a general proxy."""
import asyncio
async def forward(reader,writer):
    try:
        upstream_reader,upstream_writer=await asyncio.open_connection('homeassistant',8123)
        async def pump(src,dst):
            try:
                while data:=await src.read(65536):
                    dst.write(data);await dst.drain()
            finally:
                dst.close()
        await asyncio.gather(pump(reader,upstream_writer),pump(upstream_reader,writer))
    except (OSError,ConnectionError):
        writer.close()
async def main():
    server=await asyncio.start_server(forward,'0.0.0.0',8123)
    async with server: await server.serve_forever()
asyncio.run(main())

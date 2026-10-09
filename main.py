import asyncio
from vman_py.core.scan import PyEnvScanner

async def main():
    scanner = PyEnvScanner()
    result = await scanner.scan(".")
    print(result)

if __name__ == "__main__":
    asyncio.run(main())

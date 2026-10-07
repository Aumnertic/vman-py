from vman_py.core.scan import PyEnvScanner

def main():
    scanner = PyEnvScanner()
    result = scanner.scan(".")
    print(result)

if __name__ == "__main__":
    main()

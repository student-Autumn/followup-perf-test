import os
import time
import pytest


if __name__ == "__main__":
    pytest.main()
    time.sleep(3)
    os.system("npx -y allure-commandline generate ./temps -o ./report --clean")
    os.system("npx -y allure-commandline open ./report")


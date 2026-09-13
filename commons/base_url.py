from iniconfig import IniConfig


def read_ini():
    ini=IniConfig("./pytest.ini")
    if "base_url" not in ini:
        return {}
    else:
        return dict(ini["base_url"].items())
import os
import time
import random
import string
import yaml
from commons.base_url import read_ini
from commons.data_tag import DataTag


class DebugTalk:
    def evn(self,key):
        return read_ini()[key]

    def read_extract(self,key):
        with open(os.path.join(os.getcwd(), "extract.yaml"), encoding="utf-8", mode="r") as f:
            value=yaml.safe_load(f) or {}
            if key not in value or value[key] is None:
                return None
            return value[key]

    def timestamp(self, *args):
        """返回毫秒时间戳，用于生成唯一值"""
        return str(int(time.time() * 1000))

    def random_str(self, *args):
        """返回随机字符串，可选指定长度，默认8位"""
        length = int(args[0]) if args else 8
        return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

    def random_phone(self, *args):
        """返回随机手机号，以138开头共11位"""
        suffix = ''.join(random.choices(string.digits, k=8))
        return f'138{suffix}'

    def random_id_no(self, *args):
        """返回合法的18位身份证号，可选参数 gender: 0=女, 1=男, 不传=随机"""
        gender = int(args[0]) if args else None
        return DataTag.make_unique_id_no(gender=gender)


import os
import requests
from commons.auth_token import get_auth_headers


class RequestUtil:
    sess = requests.session()

    def _get_token_header(self):
        """从共享 .auth_token.yaml 读取 token，自动附加到所有请求"""
        return get_auth_headers()

    def all_send_request(self, **kwargs):
        if "headers" not in kwargs:
            kwargs["headers"] = {}
        if "Authorization" not in kwargs["headers"]:
            token_header = self._get_token_header()
            kwargs["headers"].update(token_header)
        res = RequestUtil.sess.request(**kwargs)
        return res
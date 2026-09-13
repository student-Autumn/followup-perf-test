import copy
import re
import yaml
import jsonpath
from commons.yaml_util import write_yaml
from hotload.debug_talk import DebugTalk


class Extraction:
    def set_extract(self,res,var_name,attr_name,expr,index):
        new_res=copy.deepcopy(res)
        try:
            new_res.json=new_res.json()
        except Exception:
            new_res.json={"msg":"response is not json"}
        data=getattr(new_res,attr_name)
        if expr.startswith("$."):
            lis=jsonpath.jsonpath(dict(data),expr)
        else:
            lis=re.findall(expr,data)
        if lis:
            write_yaml({var_name:lis[index]})
        

    def change(self,request_data):
        data_str=yaml.dump(request_data)
        new_str=self.hotload_replace(data_str)
        data_dict=yaml.safe_load(new_str)
        return data_dict

    def hotload_replace(self,data_str):
        regexp="\\$\\{(.*?)\\((.*?)\\)\\}"
        fun_list=re.findall(regexp,data_str)
        for f in fun_list:
            if f[1]=="":
                new_value=getattr(DebugTalk(),f[0])()
            else:
                new_value=getattr(DebugTalk(),f[0])(*f[1].split(","))
            if new_value is None:
                raise ValueError(
                    f"hotload 替换失败: ${{{f[0]}({f[1]})}} 的值为 null/None，"
                    f"请检查 extract.yaml 中 '{f[1]}' 是否已被正确赋值"
                )
            old_value="${"+f[0]+"("+f[1]+")}"
            data_str=data_str.replace(old_value,str(new_value))
        return data_str

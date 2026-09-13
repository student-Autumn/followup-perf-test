import copy
import re
import jsonpath


from yaml import parse


class AssertUtil:
    def assert_all_case(self,res,assert_type,value): #value [{msg:[]},{}]
        new_res=copy.deepcopy(res)
        try:
            new_res.json=new_res.json()
        except Exception:
            new_res.json={"msg":"response is not json"}
        # print("----------------------")
        # print(new_res.json)
        # print(new_res.status_code)
        for v in value: #{msg:[status_code, 200]}
            for msg,assert_data in v.items():
                sj,yq=assert_data[0],assert_data[1]
                try:
                    if(sj.startswith('json')): 
                        jsonpath_expr=self.conver_to_jsonpath(sj)
                        print("-------------------")
                        print(jsonpath_expr)
                        matches = jsonpath.jsonpath(new_res.json,jsonpath_expr)
                        print("-------------------")
                        print(matches)
                        sj_value = matches[0] if matches else None
                    else:
                        sj_value=getattr(new_res,sj)
                except Exception:
                    sj_value=sj
                #断言
                try:
                    if assert_type == "eq":
                        assert yq == sj_value, f"{msg}，期望值：{yq}，实际值：{sj_value}"
                    elif assert_type == "contains":
                        assert yq in sj_value, f"{msg}，期望值：{yq}，实际值：{sj_value}"
                    elif assert_type == "db":
                        pass
                except Exception as e:
                    raise e
    
    def conver_to_jsonpath(self,path):
        path=path.replace("json","",1)
        if "[" in path:
            keys=re.findall(r'\[(.*?)\]',path)
            jsonpath_str="$"
            for key in keys:
                if (key.startswith("'") and key.endswith("'")) or (key.startswith('"') and key.endswith('"')):
                    key = key[1:-1]
                if key.isdigit():
                    jsonpath_str +=f"[{key}]"
                else:
                    jsonpath_str +=f".{key}"
        return jsonpath_str

# if __name__=="__main__":
#     util = AssertUtil()
#     util.conver_to_jsonpat("json[data][list][0]")
                


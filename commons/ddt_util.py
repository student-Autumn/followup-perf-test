import yaml


def read_testcase(yaml_path):
    with open(yaml_path,encoding="utf-8") as f:
        case_list=yaml.safe_load(f) #[{}]
        if len(case_list)>=2:
            new_case_list=[]
            for single_case in case_list:
                if "parametrize" in single_case.keys():
                    new_case_list.extend(ddts(single_case))
                else:
                    new_case_list.append(single_case)
            return new_case_list
        else:
            if "parametrize" in dict(*case_list).keys():
                new_case=ddts(*case_list)
                return new_case #[{},{},{}]
            else:
                return case_list
            

def ddts(caseinfo:dict):
    data_list=caseinfo["parametrize"] #data_list[[],[]]
    name_len=len(data_list[0])
    len_flag=True
    for data in data_list:
        if len(data)!=name_len:
            len_flag=False
            print("参数化数据长度不一致")
            break
    str_caseinfo=yaml.dump(caseinfo) #字典转为yaml文件的字符串或文件
    new_caseinfo=[]
    if len_flag:
        for x in range(1,len(data_list)):
            raw_caseinfo=str_caseinfo
            for y in range(0,name_len):
                if isinstance(data_list[x][y],str) and data_list[x][y].isdigit():
                    data_list[x][y]="'"+data_list[x][y]+"'"
                raw_caseinfo=raw_caseinfo.replace("$ddt("+data_list[0][y]+")",str(data_list[x][y]))
            case_dict=yaml.safe_load(raw_caseinfo) #将yaml字符串转为字典
            case_dict.pop("parametrize")
            new_caseinfo.append(case_dict)
    return new_caseinfo
    
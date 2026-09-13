from dataclasses import dataclass

@dataclass
class CaseInfo:
    feature:str
    story:str
    title:str
    request:dict

    validate:dict=None
    extract:dict=None
    parametrize:list=None

def verify_yaml(caseinfo):
    try:
        new_caseinfo=CaseInfo(**caseinfo)
        return new_caseinfo
    except Exception:
        raise Exception("yaml测试用例不符合框架")

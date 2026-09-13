from pathlib import Path
import allure
import pytest
from commons.ddt_util import read_testcase
from commons.main_util import stand_cese_flow
from commons.modul_util import verify_yaml
from configs import setting

@allure.epic(setting.allure_project_name)
class TestAllCase:
    pass

def create_testcase(yaml_path):
    case=read_testcase(yaml_path)
    @pytest.mark.parametrize("caseinfo",case)
    def fun(self,caseinfo):
        case_obj=verify_yaml(caseinfo)
        stand_cese_flow(case_obj)
        allure.dynamic.feature(case_obj.feature)
        allure.dynamic.story(case_obj.story)
        allure.dynamic.title(case_obj.title)
    return fun

testcase_path=Path(__file__).parent
yaml_case_list=list(testcase_path.glob("**/*.yaml"))
yaml_case_list.sort()
for yaml_path in yaml_case_list:
    relative=yaml_path.relative_to(testcase_path)
    test_name="test_"+str(relative.with_suffix('')).replace('\\','_').replace('/','_')
    setattr(TestAllCase,test_name,create_testcase(yaml_path))


import json
import allure
from commons.assert_util import AssertUtil
from commons.extract_util import Extraction
from commons.request_util import RequestUtil

re=RequestUtil()
eu=Extraction()
ass=AssertUtil()
def stand_cese_flow(caseinfo):
    if caseinfo.request:
        new_request=eu.change(caseinfo.request)
        allure.attach(
            json.dumps(new_request, ensure_ascii=False, indent=2, default=str),
            name="请求信息",
            attachment_type=allure.attachment_type.JSON,
        )
    res=re.all_send_request(**new_request)

    # 打印响应体（方便调试）
    try:
        print(f"\n{'='*50}\n[CASE] {caseinfo.title}\n[RESPONSE] {json.dumps(res.json(), ensure_ascii=False, indent=2, default=str)}\n{'='*50}")
    except Exception:
        print(f"\n{'='*50}\n[CASE] {caseinfo.title}\n[RESPONSE] {res.text[:500]}\n{'='*50}")

    # 附加响应体
    try:
        response_body = json.dumps(res.json(), ensure_ascii=False, indent=2, default=str)
        resp_type = allure.attachment_type.JSON
    except Exception:
        response_body = res.text
        resp_type = allure.attachment_type.TEXT
    allure.attach(response_body, name="响应信息", attachment_type=resp_type)

    if caseinfo.extract:
        for key,value in caseinfo.extract.items():
            eu.set_extract(res,key,*value)

    if caseinfo.validate:
        new_validate = eu.change(caseinfo.validate)
        for assert_type,value in new_validate.items():
            ass.assert_all_case(res,assert_type,value)
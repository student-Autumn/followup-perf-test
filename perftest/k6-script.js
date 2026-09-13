/**
 * API 全量压测脚本 - k6（含认证，覆盖全部13个模块83个接口）
 * 启动: k6 run perftest/k6-script.js
 * 启动(Web报告): K6_WEB_DASHBOARD=true k6 run perftest/k6-script.js
 *
 * v2 变更: 数据池轮转 + 参数随机化
 *
 * 模块覆盖:
 *   操作日志管理   6 个接口
 *   筛查管理       6 个接口
 *   系统日志管理   2 个接口
 *   随访管理       6 个接口
 *   硬件管理       8 个接口
 *   机构管理       8 个接口
 *   角色管理       9 个接口
 *   仪表盘管理     7 个接口
 *   病人管理       6 个接口
 *   项目管理       8 个接口
 *   安全测试管理   2 个接口
 *   调查问卷管理  10 个接口
 *   用户管理       5 个接口
 */

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Counter } from 'k6/metrics';

// ==================== 自定义指标 ====================

const bizFailures = new Counter('biz_failures');
const authRequests = new Counter('auth_requests');
const publicRequests = new Counter('public_requests');

// ==================== 配置 ====================

const BASE_URL = 'http://your-api-server:8082';
const LOGIN_PHONE = '13800000000';

export const options = {
  stages: [
    { duration: '30s', target: 5 },
    { duration: '1m',  target: 10 },
    { duration: '2m',  target: 10 },
    { duration: '30s', target: 0 },
  ],
  thresholds: {
    http_req_duration: ['p(95)<2000'],
    http_req_failed:   ['rate<0.05'],
    biz_failures:      ['count<100'],
  },
};

// ==================== 读写分离 ====================

let VU_READONLY = null;  // 每个 VU 有独立的 JS 上下文

function skipIfReadonly() {
  if (VU_READONLY === null) {
    VU_READONLY = Math.random() < 0.8;  // 80% 只读
    console.log(`  [${VU_READONLY ? '只读' : '读写'}] VU 启动`);
  }
  return VU_READONLY;
}

// ==================== 真实数据 ====================

let REAL_DATA = {
  patientId: 1,
  patientName: '',
  operatorId: 1,
  opLogId: 1,
  screenRecordId: 1,
  screenProjectId: 1,
  reportId: 1,
  followupPatientId: 1,
  sysLogId: 1,
  hardwareManageId: 1,
  hardwareNo: '',
  orgId: 1,
  orgName: '',
  roleId: 1,
  roleName: '',
  idNo: '',
  projectId: 1,
  projectName: '',
  projectOrgId: 1,
  hospitalIds: [],
  regionId: 1,
  securityTestAnswerId: 1,
  surveyId: 1,
  surveyTitle: '',
  userId: 1,
  username: '',
  userPhone: '',
  // 数据池（由 fetch_real_data.py 生成）
  patientPool: [],
  screenRecordPool: [],
  opLogPool: [],
  sysLogPool: [],
  followupPool: [],
  hardwarePool: [],
  orgPool: [],
  rolePool: [],
  projectPool: [],
  surveyPool: [],
  userPool: [],
};

// ==================== 工具函数 ====================

function randomStr(len) {
  return Math.random().toString(36).substring(2, 2 + (len || 6));
}

function randomPhone() {
  return `138${String(Math.floor(Math.random() * 100000000)).padStart(8, '0')}`;
}

function randomName(prefix) {
  const surnames = ['张', '李', '王', '赵', '陈', '刘', '黄', '周', '吴', '郑'];
  return `${surnames[Math.floor(Math.random() * surnames.length)]}${prefix || '用户'}`;
}

function randomChoice(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}

function randomInt(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function randomPage() {
  return { pageNum: randomInt(1, 5), pageSize: randomChoice([5, 10, 15, 20]) };
}

function poolGet(poolKey, field, fallbackKey) {
  const pool = REAL_DATA[poolKey];
  if (pool && pool.length > 0) {
    const item = randomChoice(pool);
    if (item && item[field] !== undefined) return item[field];
  }
  if (fallbackKey) return REAL_DATA[fallbackKey];
  return REAL_DATA[field];
}

function poolItem(poolKey) {
  const pool = REAL_DATA[poolKey];
  if (pool && pool.length > 0) {
    return randomChoice(pool);
  }
  return {};
}

function fetchRealData() {
  const dataFile = './real_data.json';
  try {
    const loaded = JSON.parse(open(dataFile));
    Object.assign(REAL_DATA, loaded);
    console.log(`  [OK] 已从 ${dataFile} 加载 ${Object.keys(loaded).length} 个字段`);
  } catch (e) {
    console.warn(`  [WARN] 读取 ${dataFile} 失败: ${e}`);
    console.warn(`  [WARN] 请先运行: python scripts/fetch_real_data.py`);
  }

  // 打印数据池统计
  const poolKeys = ['patientPool', 'screenRecordPool', 'opLogPool', 'sysLogPool',
    'followupPool', 'hardwarePool', 'orgPool', 'rolePool', 'projectPool', 'surveyPool', 'userPool'];
  const stats = poolKeys.map(k => `${k}=${(REAL_DATA[k] || []).length}条`).join(' ');
  console.log(`  数据池: ${stats}`);
}

// ==================== 请求工具 ====================

function authHeaders(data) {
  if (data && data.token) {
    return { Authorization: `${data.tokenType || 'Bearer'} ${data.token}` };
  }
  return {};
}

function doPost(url, body, data, needAuth, name) {
  const headers = { 'Content-Type': 'application/json' };
  if (needAuth) {
    Object.assign(headers, authHeaders(data));
    authRequests.add(1);
  } else {
    publicRequests.add(1);
  }

  const resp = http.post(`${BASE_URL}${url}`, JSON.stringify(body), {
    headers,
    tags: { name: name || url },
  });

  const ok = check(resp, {
    [`${name || url} 状态200`]: (r) => r.status === 200,
  });

  if (ok && resp.status === 200) {
    try {
      const json = resp.json();
      if (!json.success) {
        bizFailures.add(1);
        return null;
      }
      return json;
    } catch (e) {
      bizFailures.add(1);
      return null;
    }
  }
  return null;
}

function doGet(url, data, needAuth, name) {
  const headers = {};
  if (needAuth) {
    Object.assign(headers, authHeaders(data));
    authRequests.add(1);
  } else {
    publicRequests.add(1);
  }

  const resp = http.get(`${BASE_URL}${url}`, {
    headers,
    tags: { name: name || url },
  });

  const ok = check(resp, {
    [`${name || url} 状态200`]: (r) => r.status === 200,
  });

  if (ok && resp.status === 200) {
    try {
      const json = resp.json();
      if (!json.success) {
        bizFailures.add(1);
        return null;
      }
      return json;
    } catch (e) {
      bizFailures.add(1);
      return null;
    }
  }
  return null;
}

function weightedPick(items) {
  const total = items.reduce((s, [w]) => s + w, 0);
  let r = Math.random() * total;
  for (const [w, fn] of items) {
    r -= w;
    if (r <= 0) return fn;
  }
  return items[items.length - 1][1];
}

// ==================== 各模块任务函数 ====================

// --- 操作日志管理 (6 接口) ---
function opLogTasks(data) {
  const ids = data.opLog || {};
  const oid = ids.opLogId || poolGet('opLogPool', 'id', 'opLogId');

  weightedPick([
    [4, () => doPost('/operation-log/list', randomPage(), data, false, 'POST /operation-log/list (分页)')],
    [3, () => {
      const pid = poolGet('patientPool', 'patientId', 'patientId');
      doGet(`/operation-log/patient/${pid}`, data, false, 'GET /operation-log/patient/{id}');
    }],
    [2, () => {
      if (skipIfReadonly()) return;
      const r = doPost('/operation-log/create', {
        operationTime: '2026-06-17 10:00:00',
        operationType: randomChoice(['巡检', '维修', '保养', '校准']),
        type: randomChoice(['常规操作', '紧急操作', '定期操作']),
        operator: randomName('操作员'),
        patientId: poolGet('patientPool', 'patientId', 'patientId'),
        operatorId: poolGet('opLogPool', 'operatorId', 'operatorId'),
      }, data, true, 'POST /operation-log/create');
      if (r && r.data) ids.opLogId = r.data;
    }],
    [2, () => doGet(`/operation-log/${oid}`, data, true, 'GET /operation-log/{id}')],
    [1, () => {
      if (skipIfReadonly()) return;
      doPost('/operation-log/update', {
      id: oid,
      operationTime: '2026-06-17 12:00:00',
      operationType: randomChoice(['巡检-已更新', '维修-已更新']),
      type: randomChoice(['常规操作-已更新', '紧急操作-已更新']),
      operator: randomName('操作员'),
      patientId: poolGet('patientPool', 'patientId', 'patientId'),
      operatorId: poolGet('opLogPool', 'operatorId', 'operatorId'),
    }, data, true, 'POST /operation-log/update');
    }],
    [1, () => {
      if (skipIfReadonly()) return;
      if (!ids.opLogId) return;
      doPost(`/operation-log/delete/${ids.opLogId}`, {}, data, true, 'POST /operation-log/delete/{id}');
      delete ids.opLogId;
    }],
  ])();
}

// --- 筛查管理 (6 接口) ---
function screeningTasks(data) {
  const ids = data.scr || {};
  const sid = ids.screenRecordId || poolGet('screenRecordPool', 'id', 'screenRecordId');

  weightedPick([
    [4, () => doPost('/screen/record/list', randomPage(), data, false, 'POST /screen/record/list (分页)')],
    [3, () => {
      const pid = poolGet('patientPool', 'patientId', 'patientId');
      doGet(`/screen/record/list/patient/${pid}`, data, false, 'GET /screen/record/list/patient/{id}');
    }],
    // 暂时注释：创建筛查人员记录改为测试接口，不参与压测
    // [2, () => {
    //   const r = doPost('/screen/record/create', {...}, data, true, 'POST /screen/record/create');
    //   if (r && r.data) ids.screenRecordId = r.data;
    // }],
    [2, () => doGet(`/screen/record/detail/${sid}`, data, true, 'GET /screen/record/detail/{id}')],
    [1, () => {
      if (skipIfReadonly()) return;
      doPost('/screen/record/update', {
      patientId: poolGet('patientPool', 'patientId', 'patientId'),
      address: randomChoice(['浙江省杭州市西湖区', '北京市朝阳区', '上海市浦东新区', '广东省广州市天河区']),
      emergencyContact: randomName('联系人'),
      emergencyPhone: randomPhone(),
    }, data, true, 'POST /screen/record/update')],
    [1, () => {
      if (skipIfReadonly()) return;
      if (!ids.screenRecordId) return;
      doPost(`/screen/record/delete/${ids.screenRecordId}`, {}, data, true, 'POST /screen/record/delete/{id}');
      delete ids.screenRecordId;
    }],
  ])();
}

// --- 系统日志管理 (2 接口) ---
function systemLogTasks(data) {
  weightedPick([
    [4, () => doPost('/system/log/list', randomPage(), data, false, 'POST /system/log/list (默认)')],
    [3, () => {
      const params = randomPage();
      params.type = randomChoice(['ERROR', 'WARN', 'INFO', 'DEBUG']);
      doPost('/system/log/list', params, data, false, 'POST /system/log/list (按类型)');
    }],
    [2, () => {
      const params = randomPage();
      params.keyword = randomChoice(['登录', '创建', '删除', '更新', '查询', '认证']);
      doPost('/system/log/list', params, data, false, 'POST /system/log/list (关键字)');
    }],
    [1, () => {
      const sid = poolGet('sysLogPool', 'id', 'sysLogId');
      doGet(`/system/log/${sid}`, data, false, 'GET /system/log/{id}');
    }],
  ])();
}

// --- 随访管理 (6 接口) ---
function followupTasks(data) {
  weightedPick([
    [4, () => doPost('/followup/record/list', randomPage(), data, false, 'POST /followup/record/list (分页)')],
    [3, () => {
      const rid = poolGet('followupPool', 'reportId', 'reportId');
      doGet(`/followup/record/detail/${rid}`, data, false, 'GET /followup/record/detail/{id}');
    }],
    [2, () => {
      const rid = poolGet('followupPool', 'reportId', 'reportId');
      doGet(`/followup/record/report/${rid}`, data, false, 'GET /followup/record/report/{id}');
    }],
    [2, () => doPost('/followup/record/send-notification', {
      patientId: poolGet('patientPool', 'patientId', 'patientId'),
      content: randomChoice([
        '您的随访报告已生成，请及时查看',
        '请按时参加下一次随访',
        '您的检查结果已出，请联系医生',
      ]),
      isUrgent: randomChoice([true, false]),
    }, data, false, 'POST /followup/record/send-notification')],
    [1, () => {
      const pid = poolGet('patientPool', 'patientId', 'patientId');
      doGet(`/followup/record/call-records/${pid}`, data, true, 'GET /followup/record/call-records/{id}');
    }],
    [1, () => {
      if (skipIfReadonly()) return;
      const rid = poolGet('followupPool', 'reportId', 'reportId');
      const pid = poolGet('followupPool', 'patientId', 'followupPatientId');
      doPost('/followup/record/update', {
        reportId: rid,
        patientId: pid,
        address: randomChoice(['浙江省杭州市西湖区', '北京市朝阳区', '上海市浦东新区']),
        emergencyContact: randomName('联系人'),
        emergencyPhone: randomPhone(),
        followupLevel: randomChoice(['一级', '二级', '三级']),
        followupCycle: randomChoice(['每月', '每季', '每年']),
        patientDisease: randomChoice(['肠癌术后', '肺癌术后', '胃癌术后']),
        positiveLevel: randomChoice(['阳性', '阴性', '疑似']),
        interventionMeasures: randomChoice(['定期复查', '药物治疗', '手术治疗']),
        interpretationResult: randomChoice(['建议进一步检查', '结果正常', '需持续观察']),
      }, data, true, 'POST /followup/record/update');
    }],
  ])();
}

// --- 硬件管理 (8 接口) ---
function hardwareTasks(data) {
  const ids = data.hw || {};
  const hwId = ids.hardwareManageId || poolGet('hardwarePool', 'id', 'hardwareManageId');

  weightedPick([
    [3, () => doPost('/hardware-manage/list', randomPage(), data, false, 'POST /hardware-manage/list (分页)')],
    [3, () => doGet('/hardware-manage/all', data, false, 'GET /hardware-manage/all')],
    [2, () => {
      const hid = poolGet('hardwarePool', 'id', 'hardwareManageId');
      doGet(`/hardware-manage/${hid}`, data, false, 'GET /hardware-manage/{id}');
    }],
    [2, () => {
      const hno = poolGet('hardwarePool', 'hardwareNo', 'hardwareNo');
      doGet(`/hardware-manage/by-hardware-no/${encodeURIComponent(hno)}`, data, false, 'GET /hardware-manage/by-hardware-no/{no}');
    }],
    [1, () => {
      if (skipIfReadonly()) return;
      const hwNo = `HW-PERF-${Date.now()}`;
      const r = doPost('/hardware-manage/create', {
        hardwareNo: hwNo,
        hardwareType: randomChoice([1, 2, 3]),
      }, data, true, 'POST /hardware-manage/create');
      if (r && r.data) { ids.hardwareManageId = r.data; ids.hardwareNo = hwNo; }
    }],
    [1, () => {
      if (skipIfReadonly()) return;
      doPost('/hardware-manage/update', {
      id: hwId,
      hardwareNo: ids.hardwareNo || poolGet('hardwarePool', 'hardwareNo', 'hardwareNo'),
      hardwareType: randomChoice([1, 2, 3]),
      organizationId: poolGet('orgPool', 'id', 'orgId'),
    }, data, true, 'POST /hardware-manage/update')],
    [1, () => {
      if (skipIfReadonly()) return;
      if (!ids.hardwareManageId) return;
      doPost(`/hardware-manage/delete/${ids.hardwareManageId}`, {}, data, true, 'POST /hardware-manage/delete/{id}');
      delete ids.hardwareManageId;
    }],
    [1, () => {
      if (skipIfReadonly()) return;
      if (!ids.hardwareManageId) return;
      doPost('/hardware-manage/batch/delete', [ids.hardwareManageId], data, true, 'POST /hardware-manage/batch/delete');
      delete ids.hardwareManageId;
    }],
  ])();
}

// --- 机构管理 (8 接口) ---
function organizationTasks(data) {
  const ids = data.org || {};
  const orgId = ids.orgId || poolGet('orgPool', 'id', 'orgId');

  weightedPick([
    [3, () => doPost('/organization/list', randomPage(), data, false, 'POST /organization/list (分页)')],
    [3, () => doGet('/organization/all', data, false, 'GET /organization/all')],
    [2, () => {
      const oid = poolGet('orgPool', 'id', 'orgId');
      doGet(`/organization/detail/${oid}`, data, false, 'GET /organization/detail/{id}');
    }],
    [2, () => {
      const org = poolItem('orgPool');
      const name = org.orgName || REAL_DATA.orgName;
      doGet(`/organization/search?orgName=${encodeURIComponent(name)}`, data, false, 'GET /organization/search');
    }],
    [1, () => {
      if (skipIfReadonly()) return;
      const r = doPost('/organization/create', {
        orgName: `测试机构-PERF-${Date.now()}`,
        orgType: randomChoice([1, 2]),
        regionId: poolGet('orgPool', 'id', 'orgId'),
        contactPerson: randomName('联系人'),
        contactInfo: randomPhone(),
      }, data, true, 'POST /organization/create');
      if (r && r.data) ids.orgId = r.data;
    }],
    [1, () => {
      if (skipIfReadonly()) return;
      doPost('/organization/update', {
      id: orgId,
      orgType: randomChoice([1, 2]),
      regionId: poolGet('orgPool', 'id', 'orgId'),
      contactPerson: randomName('联系人'),
      contactInfo: randomPhone(),
    }, data, true, 'POST /organization/update')],
    [1, () => {
      if (skipIfReadonly()) return;
      if (!ids.orgId) return;
      doPost(`/organization/delete/${ids.orgId}`, {}, data, true, 'POST /organization/delete/{id}');
      delete ids.orgId;
    }],
    [1, () => {
      if (skipIfReadonly()) return;
      if (!ids.orgId) return;
      doPost('/organization/batch/delete', [ids.orgId], data, true, 'POST /organization/batch/delete');
      delete ids.orgId;
    }],
  ])();
}

// --- 角色管理 (9 接口) ---
function roleTasks(data) {
  weightedPick([
    [3, () => doPost('/role/list', randomPage(), data, false, 'POST /role/list (分页)')],
    [3, () => doGet('/role/all', data, false, 'GET /role/all')],
    [2, () => {
      const rid = poolGet('rolePool', 'id', 'roleId');
      doGet(`/role/detail/${rid}`, data, false, 'GET /role/detail/{id}');
    }],
    [2, () => {
      const rid = poolGet('rolePool', 'id', 'roleId');
      doGet(`/role/function-permissions/${rid}`, data, false, 'GET /role/function-permissions/{id}');
    }],
    [1, () => {
      if (skipIfReadonly()) return;
      doPost('/role/add', {
      roleName: `perf_${randomStr(6)}`,
      roleKey: `perf_${randomStr(6)}`,
      description: randomChoice(['压测创建', '自动化测试角色', '临时角色']),
      dataScope: randomChoice([1, 2]),
      status: 1,
    }, data, true, 'POST /role/add');
    }],
    [1, () => {
      if (skipIfReadonly()) return;
      const rid = poolGet('rolePool', 'id', 'roleId');
      doPost('/role/update', {
        id: rid,
        roleName: `压测角色-${randomStr(4)}`,
        roleKey: `perf_role_${randomStr(4)}`,
        description: randomChoice(['压测更新', '已更新角色']),
        dataScope: randomChoice([1, 2]),
        status: 1,
      }, data, true, 'POST /role/update');
    }],
    [1, () => {
      if (skipIfReadonly()) return;
      const rid = poolGet('rolePool', 'id', 'roleId');
      doPost('/role/function-permission/update', {
        roleId: rid,
        functionPermissionIds: [],
      }, data, true, 'POST /role/function-permission/update');
    }],
    [1, () => {
      if (skipIfReadonly()) return;
      const rid = poolGet('rolePool', 'id', 'roleId');
      doPost('/role/data-permission/update', {
        roleId: rid,
        dataScope: randomChoice([1, 2]),
      }, data, true, 'POST /role/data-permission/update');
    }],
    [1, () => {
      if (skipIfReadonly()) return;
      if (!ids.roleId) return;
      doPost(`/role/delete/${ids.roleId}`, {}, data, true, 'POST /role/delete/{id}');
      delete ids.roleId;
    }],
  ])();
}

// --- 仪表盘管理 (7 接口) ---
function dashboardTasks(data) {
  weightedPick([
    [2, () => doGet('/dashboard/statistics/screen', data, false, 'GET /dashboard/statistics/screen')],
    [2, () => {
      const endDate = new Date(2026, 5, 24 - randomInt(0, 7));  // June=5
      const startDate = new Date(endDate.getTime() - randomInt(3, 30) * 86400000);
      const fmt = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
      doGet(`/dashboard/statistics/screen-daily?startDate=${fmt(startDate)}&endDate=${fmt(endDate)}`, data, false, 'GET /dashboard/statistics/screen-daily');
    }],
    [2, () => doGet('/dashboard/statistics/registration', data, false, 'GET /dashboard/statistics/registration')],
    [2, () => doGet(`/dashboard/statistics/org-ranking?rankType=${randomChoice([1, 2])}`, data, false, 'GET /dashboard/statistics/org-ranking')],
    [1, () => doGet(`/dashboard/statistics/org-ranking?rankType=${randomChoice([1, 2])}`, data, false, 'GET /dashboard/statistics/org-ranking')],
    [2, () => doGet('/dashboard/statistics/hardware-bind', data, false, 'GET /dashboard/statistics/hardware-bind')],
    [2, () => {
      const endDate = new Date(2026, 5, 24 - randomInt(0, 7));
      const startDate = new Date(endDate.getTime() - randomInt(3, 30) * 86400000);
      const fmt = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
      doGet(`/dashboard/statistics/hardware-bind-daily?startDate=${fmt(startDate)}&endDate=${fmt(endDate)}`, data, false, 'GET /dashboard/statistics/hardware-bind-daily');
    }],
    [2, () => doGet('/dashboard/statistics/gender-ratio', data, false, 'GET /dashboard/statistics/gender-ratio')],
  ])();
}

// --- 病人管理 (6 接口) ---
function patientTasks(data) {
  weightedPick([
    [3, () => doPost('/patient/list', randomPage(), data, false, 'POST /patient/list (分页)')],
    [2, () => {
      const pid = poolGet('patientPool', 'patientId', 'patientId');
      doGet(`/patient/${pid}`, data, false, 'GET /patient/{patientId}');
    }],
    [2, () => {
      const pat = poolItem('patientPool');
      const idNo = pat.idNo || REAL_DATA.idNo;
      doGet(`/patient/by-idcard/${idNo}`, data, false, 'GET /patient/by-idcard/{idNo}');
    }],
    [1, () => {
      if (skipIfReadonly()) return;
      doPost('/patient/create', {
      name: randomName('病人'),
      age: randomInt(18, 80),
      gender: randomChoice([0, 1]),
      idNo: `ID${Date.now()}`,
      address: randomChoice(['浙江省杭州市西湖区', '北京市朝阳区', '上海市浦东新区']),
      emergencyContact: randomName('联系人'),
      emergencyPhone: randomPhone(),
    }, data, true, 'POST /patient/create')],
    [1, () => {
      if (skipIfReadonly()) return;
      const pid = poolGet('patientPool', 'patientId', 'patientId');
      doPost('/patient/update', {
        patientId: pid,
        name: randomName('病人'),
        age: randomInt(18, 80),
        gender: randomChoice([0, 1]),
        address: randomChoice(['更新后地址A', '更新后地址B', '更新后地址C']),
        emergencyContact: randomName('联系人'),
        emergencyPhone: randomPhone(),
      }, data, true, 'POST /patient/update');
    }],
    [1, () => {
      if (skipIfReadonly()) return;
      if (!ids.patientId) return;
      doPost(`/patient/delete/${ids.patientId}`, {}, data, true, 'POST /patient/delete/{patientId}');
      delete ids.patientId;
    }],
  ])();
}

// --- 项目管理 (8 接口) ---
function projectTasks(data) {
  const ids = data.prj || {};
  const pid = ids.projectId || poolGet('projectPool', 'id', 'projectId');

  weightedPick([
    [3, () => doPost('/project/list', randomPage(), data, false, 'POST /project/list (分页)')],
    [3, () => doGet('/project/all', data, false, 'GET /project/all')],
    [2, () => {
      const prid = poolGet('projectPool', 'id', 'projectId');
      doGet(`/project/detail/${prid}`, data, false, 'GET /project/detail/{id}');
    }],
    [1, () => {
      if (skipIfReadonly()) return;
      const proj = poolItem('projectPool');
      const r = doPost('/project/create', {
        projectName: `压测项目-${Date.now()}`,
        projectStatus: randomChoice([0, 1]),
        screenDate: '2026-06-23',
        hospitalIds: proj.hospitalIds || REAL_DATA.hospitalIds,
        organizationId: proj.organizationId || REAL_DATA.projectOrgId,
        regionId: proj.regionId || REAL_DATA.regionId,
      }, data, true, 'POST /project/create');
      if (r && r.data) ids.projectId = r.data;
    }],
    [1, () => {
      if (skipIfReadonly()) return;
      const proj = poolItem('projectPool');
      doPost('/project/update', {
        id: pid,
        projectName: `压测项目-已更新-${randomStr(4)}`,
        projectStatus: randomChoice([0, 1]),
        screenDate: '2026-06-24',
        hospitalIds: proj.hospitalIds || REAL_DATA.hospitalIds,
        organizationId: proj.organizationId || REAL_DATA.projectOrgId,
        regionId: proj.regionId || REAL_DATA.regionId,
      }, data, true, 'POST /project/update');
    }],
    [1, () => {
      if (skipIfReadonly()) return;
      doPost(`/project/update/status?id=${pid}&status=${randomChoice([0, 1])}`, {}, data, true, 'POST /project/update/status');
    }],
    [1, () => {
      if (skipIfReadonly()) return;
      if (!ids.projectId) return;
      doPost(`/project/delete/${ids.projectId}`, {}, data, true, 'POST /project/delete/{id}');
      delete ids.projectId;
    }],
    [1, () => {
      if (skipIfReadonly()) return;
      if (!ids.projectId) return;
      doPost('/project/delete/batch', [ids.projectId], data, true, 'POST /project/delete/batch');
      delete ids.projectId;
    }],
  ])();
}

// --- 安全测试管理 (2 接口) ---
function securityTestTasks(data) {
  weightedPick([
    [3, () => {
      const pid = poolGet('patientPool', 'patientId', 'patientId');
      doGet(`/security-test/answers/${pid}`, data, false, 'GET /security-test/answers/{patientId}');
    }],
    [2, () => {
      if (skipIfReadonly()) return;
      const pid = poolGet('patientPool', 'patientId', 'patientId');
      doPost('/security-test/answers', {
        patientId: pid,
        submitTime: '2026-06-23T10:00:00',
        answers: [
          { questionNo: 1, question: '您是否有高血压病史？', answer: randomChoice([0, 1]) },
          { questionNo: 2, question: '您是否有糖尿病病史？', answer: randomChoice([0, 1]) },
          { questionNo: 3, question: '您是否有心脏病史？', answer: randomChoice([0, 1]) },
        ],
      }, data, true, 'POST /security-test/answers');
    }],
  ])();
}

// --- 调查问卷管理 (10 接口) ---
function surveyTasks(data) {
  const ids = data.srv || {};
  const sid = ids.surveyId || poolGet('surveyPool', 'id', 'surveyId');

  weightedPick([
    [2, () => doPost('/survey/list', randomPage(), data, false, 'POST /survey/list (分页)')],
    [2, () => doGet('/survey/list/enabled', data, false, 'GET /survey/list/enabled')],
    [2, () => {
      const svid = poolGet('surveyPool', 'id', 'surveyId');
      doGet(`/survey/detail/${svid}`, data, false, 'GET /survey/detail/{id}');
    }],
    [2, () => {
      const svid = poolGet('surveyPool', 'id', 'surveyId');
      doGet(`/survey/questions/${svid}`, data, false, 'GET /survey/questions/{surveyId}');
    }],
    [1, () => {
      const svid = poolGet('surveyPool', 'id', 'surveyId');
      doGet(`/survey/answers/${svid}`, data, false, 'GET /survey/answers/{surveyId}');
    }],
    [1, () => {
      if (skipIfReadonly()) return;
      const qCount = randomInt(2, 5);
      const questions = [];
      for (let i = 0; i < qCount; i++) {
        questions.push({
          content: `问题${i + 1}: 您对服务满意吗？`,
          questionType: randomChoice([1, 2]),
          options: [
            { key: 'A', label: randomChoice(['非常满意', '是', '很好']) },
            { key: 'B', label: randomChoice(['满意', '否', '一般']) },
            { key: 'C', label: randomChoice(['一般', '不确定', '较差']) },
            { key: 'D', label: randomChoice(['不满意', '', '很差']) },
          ],
          sortOrder: i + 1,
        });
      }
      const r = doPost('/survey/create', {
        title: `压测问卷-${Date.now()}`,
        questions: questions,
      }, data, true, 'POST /survey/create');
      if (r && r.data) ids.surveyId = r.data;
    }],
    [1, () => {
      if (skipIfReadonly()) return;
      doPost('/survey/update', {
      id: sid,
      title: `压测问卷-已更新-${randomStr(4)}`,
      status: randomChoice([0, 1]),
    }, data, true, 'POST /survey/update')],
    [1, () => {
      if (skipIfReadonly()) return;
      doPost(`/survey/update/status?id=${sid}&status=${randomChoice([0, 1])}`, {}, data, true, 'POST /survey/update/status');
    }],
    [1, () => {
      if (skipIfReadonly()) return;
      const uid = poolGet('patientPool', 'patientId', 'patientId');
      doPost('/survey/submit', {
        userId: uid,
        surveyId: sid,
        answerJson: { q_1: ['A'], q_2: ['B'] },
      }, data, true, 'POST /survey/submit');
    }],
    [1, () => {
      if (skipIfReadonly()) return;
      if (!ids.surveyId) return;
      doPost(`/survey/delete/${ids.surveyId}`, {}, data, true, 'POST /survey/delete/{id}');
      delete ids.surveyId;
    }],
    [1, () => {
      if (skipIfReadonly()) return;
      if (!ids.surveyId) return;
      doPost('/survey/delete/batch', [ids.surveyId], data, true, 'POST /survey/delete/batch');
      delete ids.surveyId;
    }],
  ])();
}

// --- 用户管理 (5 接口) ---
function userTasks(data) {
  weightedPick([
    [3, () => doGet(`/user/list?pageNum=${randomInt(1, 5)}&pageSize=${randomChoice([5, 10, 15, 20])}`, data, false, 'GET /user/list (分页)')],
    [3, () => {
      const u = poolItem('userPool');
      const name = u.username || REAL_DATA.username;
      doGet(`/user/list?pageNum=1&pageSize=10&username=${encodeURIComponent(name)}`, data, false, 'GET /user/list (按用户名)');
    }],
    [2, () => {
      const uid = poolGet('userPool', 'id', 'userId');
      doGet(`/user/detail/${uid}`, data, false, 'GET /user/detail/{id}');
    }],
    [1, () => {
      if (skipIfReadonly()) return;
      doPost('/user/create', {
      username: randomName('用户'),
      loginAccount: `perf_${Date.now()}`,
      phone: randomPhone(),
      orgId: poolGet('orgPool', 'id', 'orgId'),
      status: randomChoice([0, 1]),
      roleIds: [poolGet('rolePool', 'id', 'roleId')],
    }, data, true, 'POST /user/create')],
    [1, () => {
      if (skipIfReadonly()) return;
      const uid = poolGet('userPool', 'id', 'userId');
      doPost('/user/update', {
        id: uid,
        username: randomName('用户'),
        loginAccount: REAL_DATA.userPhone,
        phone: REAL_DATA.userPhone,
        roleIds: [poolGet('rolePool', 'id', 'roleId')],
      }, data, true, 'POST /user/update');
    }],
    [1, () => {
      if (skipIfReadonly()) return;
      if (!ids.userId) return;
      doPost(`/user/delete/${ids.userId}`, {}, data, true, 'POST /user/delete/{id}');
      delete ids.userId;
    }],
  ])();
}

// ==================== k6 生命周期 ====================

export function setup() {
  console.log(`\n  ==================================================`);
  console.log(`  目标服务器 : ${BASE_URL}`);
  console.log(`  登录账号   : ${LOGIN_PHONE}`);
  console.log(`  接口总数   : 83 个 (公开 + 认证)  v2: 数据池轮转`);
  console.log(`  ==================================================\n`);

  // 从 .auth_token.json 加载共享 token
  let token = null;
  let tokenType = 'Bearer';

  try {
    const tokenFile = open('../.auth_token.json', 'r');
    const tokenData = JSON.parse(tokenFile);
    tokenFile.close();

    if (tokenData.token && tokenData.expiresAt) {
      const expiry = new Date(tokenData.expiresAt).getTime();
      if (Date.now() < expiry - 300000) {
        token = tokenData.token;
        tokenType = tokenData.tokenType || 'Bearer';
        console.log('  [OK] 已加载共享 token');
      } else {
        console.warn('  [WARN] token 已过期，请运行: python scripts/auth_helper.py');
      }
    }
  } catch (e) {
    console.warn('  [WARN] 未找到共享 token 文件，认证接口将失败');
    console.warn('  请先运行: python scripts/auth_helper.py');
  }

  // 加载真实数据（含数据池）
  fetchRealData();

  return {
    token: token,
    tokenType: tokenType,
    opLog: {},
    scr: {},
    hw: {},
    org: {},
    prj: {},
    srv: {},
    usr: {},
  };
}

export default function (setupData) {
  const data = {
    token: setupData.token,
    tokenType: setupData.tokenType,
    opLog: Object.assign({}, setupData.opLog),
    scr: Object.assign({}, setupData.scr),
    hw: Object.assign({}, setupData.hw),
    org: Object.assign({}, setupData.org),
    prj: Object.assign({}, setupData.prj),
    srv: Object.assign({}, setupData.srv),
    usr: Object.assign({}, setupData.usr),
  };

  const pickModule = weightedPick.bind(null, [
    [2, () => userTasks(data)],
    [2, () => surveyTasks(data)],
    [2, () => securityTestTasks(data)],
    [3, () => projectTasks(data)],
    [3, () => patientTasks(data)],
    [3, () => dashboardTasks(data)],
    [3, () => followupTasks(data)],
    [3, () => screeningTasks(data)],
    [3, () => hardwareTasks(data)],
    [3, () => organizationTasks(data)],
    [3, () => roleTasks(data)],
    [2, () => systemLogTasks(data)],
    [2, () => opLogTasks(data)],
  ]);

  group('API 全量压测', () => {
    pickModule();
  });

  sleep(1);
}

// ==================== 运行结束摘要 ====================

export function handleSummary(data) {
  return {
    'perftest/k6-summary.json': JSON.stringify(data, null, 2),
    stdout: `
============================================================
  k6 压测结果摘要
============================================================
  总请求数      : ${data.metrics.http_reqs?.values?.count || 0}
  失败请求      : ${data.metrics.http_req_failed?.values?.fails || 0}
  业务失败      : ${data.metrics.biz_failures?.values?.count || 0}
  平均响应(ms)  : ${(data.metrics.http_req_duration?.values?.avg || 0).toFixed(1)}
  P95 响应(ms)  : ${data.metrics.http_req_duration?.values['p(95)'] || 0}
  认证请求      : ${data.metrics.auth_requests?.values?.count || 0}
  公开请求      : ${data.metrics.public_requests?.values?.count || 0}
============================================================
`,
  };
}

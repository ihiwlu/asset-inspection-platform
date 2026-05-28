# 数据库设计

本项目当前采用 SQLAlchemy ORM 设计数据库模型，默认使用 SQLite。

## users

用户表，用于后台登录和后续权限扩展。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | Integer | 主键 |
| username | String | 用户名，唯一 |
| password_hash | String | 加密后的密码 |
| role | String | 用户角色，例如 admin |
| created_at | DateTime | 创建时间 |

## assets

资产表，用于记录内网服务器、网络设备、终端、数据库等资产。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | Integer | 主键 |
| name | String | 资产名称 |
| ip_address | String | IP 地址，唯一 |
| asset_type | String | 资产类型 |
| status | String | 在线状态，unknown / online / offline |
| created_at | DateTime | 创建时间 |

## scan_tasks

扫描任务表，用于记录一次 IP 存活探测或端口扫描任务。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | Integer | 主键 |
| task_name | String | 任务名称 |
| scan_type | String | 扫描类型，例如 ping / port |
| target | String | 扫描目标 |
| ports | String | 端口范围，例如 22,80,443 |
| status | String | 任务状态，pending / running / finished / failed |
| created_at | DateTime | 创建时间 |

## scan_results

扫描结果表，用于保存开放端口、服务名称和风险等级。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | Integer | 主键 |
| task_id | Integer | 所属扫描任务 ID |
| asset_id | Integer | 所属资产 ID |
| ip_address | String | IP 地址 |
| port | Integer | 端口 |
| service_name | String | 服务名称 |
| status | String | 端口状态，例如 open |
| risk_level | String | 风险等级，info / low / medium / high / critical |
| scanned_at | DateTime | 扫描时间 |

## vulnerabilities

漏洞信息表，用于手动录入或根据扫描结果生成风险项。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | Integer | 主键 |
| asset_id | Integer | 所属资产 ID |
| title | String | 漏洞标题 |
| risk_level | String | 风险等级 |
| description | Text | 漏洞描述 |
| suggestion | Text | 修复建议 |
| status | String | 处理状态，open / fixed / ignored |
| created_at | DateTime | 创建时间 |

## 表关系

- 一个资产可以拥有多条扫描结果。
- 一个资产可以拥有多条漏洞信息。
- 一个扫描任务可以产生多条扫描结果。

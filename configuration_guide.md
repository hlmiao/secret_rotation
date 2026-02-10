# RDS 口令轮转系统 - 详细配置指南

本文档提供**精确的资源配置细节**，包括具体的资源名称、ARN、参数值和配置步骤。

---

## 📋 目录

1. [DSG 账号（网关账号）详细配置](#一dsg-账号网关账号详细配置)
2. [子账号（成员账号）详细配置](#二子账号成员账号详细配置)

---

## 一、DSG 账号（网关账号）详细配置

**账号 ID**: `444*********`  
**区域**: 中国区 `cn-north-1` (北京) 或 `cn-northwest-1` (宁夏)  

---

### 1.1 DynamoDB 表配置

#### 表 1: rds-metadata（元数据表）

**完整配置参数**:

| 参数 | 值 |
|-----|---|
| Table name | `rds-metadata` |
| Partition key | `account_id` (String) |
| Sort key | `secret_name` (String) |
| Table class | Standard |
| Capacity mode | On-demand |
| Encryption | AWS owned key |
| Point-in-time recovery | Disabled (可选启用) |
| Deletion protection | Disabled (生产环境建议启用) |

**ARN**: `arn:aws-cn:dynamodb:cn-north-1:444*********:table/rds-metadata`

**数据项结构**:
```json
{
  "account_id": "286*********",
  "secret_name": "test/dsg/mysql1",
  "rds_instance": "dsg-mysql-dev-1",
  "dsg_connection_name": "dsg-mysql-dev-1",
  "region": "cn-north-1",
  "db_type": "mysql",
  "enabled": true,
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z"
}
```


**字段说明**:
- `account_id` (必需): AWS 子账号 ID，12 位数字
- `secret_name` (必需): Secrets Manager 中的 Secret 完整路径
- `rds_instance` (必需): RDS 实例标识符或数据库主机名
- `dsg_connection_name` (可选): DSG 中的数据库连接名称，如不填则使用 `rds_instance`
- `region` (可选): RDS 所在区域，默认使用 Lambda 所在区域
- `db_type` (可选): 数据库类型 (mysql, oracle, postgresql 等)
- `enabled` (可选): 是否启用同步，默认 true

---

#### 表 2: rds-rotation-state（状态表）

**完整配置参数**:

| 参数 | 值 |
|-----|---|
| Table name | `rds-rotation-state` |
| Partition key | `account_id` (String) |
| Sort key | `timestamp` (String) |
| Table class | Standard |
| Capacity mode | On-demand |
| Encryption | AWS owned key |

**全局二级索引 (GSI)**:

| 参数 | 值 |
|-----|---|
| Index name | `secret-name-index` |
| Partition key | `secret_name` (String) |
| Sort key | `timestamp` (String) |
| Projection type | All |

**ARN**: 
- 表: `arn:aws-cn:dynamodb:cn-north-1:444*********:table/rds-rotation-state`
- 索引: `arn:aws-cn:dynamodb:cn-north-1:444*********:table/rds-rotation-state/index/secret-name-index`

**数据项结构**:
```json
{
  "account_id": "286*********",
  "timestamp": "2024-01-15T10:35:22.123Z",
  "secret_name": "test/dsg/mysql1",
  "status": "SUCCESS",
  "last_updated": "2024-01-15T10:35:22.123Z",
  "metadata": {
    "rds_instance": "dsg-mysql-dev-1",
    "dsg_connection_name": "dsg-mysql-dev-1",
    "region": "cn-north-1"
  }
}
```

**状态值**:
- `SUCCESS`: 同步成功
- `FAILED`: 同步失败
- `SKIPPED`: 跳过同步

---

### 1.2 IAM 角色配置

#### 角色: RDSRotationGatewayLambdaRole

**完整配置参数**:

| 参数 | 值 |
|-----|---|
| Role name | `RDSRotationGatewayLambdaRole` |
| Trusted entity | AWS service: lambda.amazonaws.com |
| Description | Lambda 执行角色用于 RDS 口令同步到 DSG |
| Max session duration | 1 hour (3600 seconds) |
| Path | / |

**ARN**: `arn:aws-cn:iam::444*********:role/RDSRotationGatewayLambdaRole`


**信任策略 (Trust Policy)**:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

**托管策略 (Managed Policies)**:
- `arn:aws-cn:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole`

**内联策略 (Inline Policy)**: `RDSRotationSyncPolicy`

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DynamoDBAccess",
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:Query",
        "dynamodb:Scan"
      ],
      "Resource": [
        "arn:aws-cn:dynamodb:cn-north-1:444*********:table/rds-metadata",
        "arn:aws-cn:dynamodb:cn-north-1:444*********:table/rds-rotation-state",
        "arn:aws-cn:dynamodb:cn-north-1:444*********:table/rds-rotation-state/index/*"
      ]
    },
    {
      "Sid": "AssumeRoleAccess",
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": "arn:aws-cn:iam::*:role/RDSRotationSyncRole"
    }
  ]
}
```

**关键点**:
- ✅ DynamoDB 资源 ARN 包含完整账号 ID `444*********`
- ✅ `sts:AssumeRole` 资源使用通配符 `*` 支持所有子账号
- ✅ 包含 DynamoDB 索引访问权限 `table/rds-rotation-state/index/*`

---

### 1.3 Lambda 函数配置

#### 函数: rds-rotation-gateway

**基本配置**:

| 参数 | 值 |
|-----|---|
| Function name | `rds-rotation-gateway` |
| Runtime | Python 3.11 |
| Architecture | x86_64 |
| Handler | `lambda_function.lambda_handler` |
| Execution role | `RDSRotationGatewayLambdaRole` |
| Memory | 512 MB |
| Timeout | 15 min 0 sec (900 seconds) |
| Ephemeral storage | 512 MB |

**ARN**: `arn:aws-cn:lambda:cn-north-1:444*********:function:rds-rotation-gateway`


**环境变量 (Environment Variables)**:

| Key | Value | 说明 |
|-----|-------|------|
| `STATE_TABLE_NAME` | `rds-rotation-state` | 状态表名称 |
| `METADATA_TABLE_NAME` | `rds-metadata` | 元数据表名称 |
| `DSG_API_ENDPOINT` | `https://10.2.*.*` | DSG API 基础 URL（不含 /api/v1） |
| `DSG_API_KEY` | `<你的DSG AccessKey>` | DSG AccessKey（用于换取 Token） |
| `CROSS_ACCOUNT_ROLE_NAME` | `RDSRotationSyncRole` | 子账号中的跨账号角色名称 |

**环境变量说明**:
- `DSG_API_ENDPOINT`: 只填写基础 URL，代码会自动拼接 `/api/v1/tokens` 等路径
- `DSG_API_KEY`: 这是 DSG 的 AccessKey（不是 Token），Token 是临时生成的
- `CROSS_ACCOUNT_ROLE_NAME`: 必须与所有子账号中的角色名称保持一致

**代码文件**:
- 主文件: `lambda_function.py` (从 `lambda/sync_engine_with_account.py` 复制)
- 大小: 约 15 KB
- 依赖: 仅使用 Python 标准库（urllib, json, boto3）

**VPC 配置** (如果 DSG 在 VPC 内):

| 参数 | 值 |
|-----|---|
| VPC | DSG 所在的 VPC ID (例如: vpc-0abc123def456789) |
| Subnets | 至少 2 个私有子网 (例如: subnet-0abc123, subnet-0def456) |
| Security groups | Lambda 安全组 (例如: sg-0abc123def456789) |

**安全组规则** (Lambda 安全组):
- Outbound: HTTPS (443) → 0.0.0.0/0 或 DSG 安全组
- Outbound: HTTPS (443) → DSG IP (10.2.*.*/32)

**重要**: 如果使用 VPC Lambda，确保子网有 NAT Gateway 或配置 VPC Endpoints (DynamoDB, Secrets Manager, STS)

**并发配置**:
- Reserved concurrency: 不设置（使用账号级并发）
- Provisioned concurrency: 0（按需调用）

**日志配置**:
- Log group: `/aws/lambda/rds-rotation-gateway`
- Retention: 7 days (可调整为 30 days)
- Log format: Text

---

### 1.4 EventBridge 定时规则配置

#### 规则: rds-rotation-sync-schedule

**完整配置参数**:

| 参数 | 值 |
|-----|---|
| Name | `rds-rotation-sync-schedule` |
| Description | 每小时触发 RDS 口令同步到 DSG |
| Event bus | default |
| Rule type | Schedule |
| Schedule pattern | Rate expression |
| Rate | `rate(1 hour)` |
| State | Enabled |

**ARN**: `arn:aws-cn:events:cn-north-1:444*********:rule/rds-rotation-sync-schedule`

**目标 (Target)**:

| 参数 | 值 |
|-----|---|
| Target type | AWS service |
| Service | Lambda function |
| Function | `rds-rotation-gateway` |
| Input | Constant (JSON text) - 空 `{}` 或不设置 |
| Retry policy | Default (2 retries, 60s max age) |
| Dead-letter queue | 不设置（可选配置 SQS） |

**Cron 表达式替代方案**:
- 每小时: `rate(1 hour)` 或 `cron(0 * * * ? *)`
- 每 2 小时: `rate(2 hours)` 或 `cron(0 */2 * * ? *)`
- 每天凌晨 2 点: `cron(0 2 * * ? *)`
- 每周一凌晨 2 点: `cron(0 2 ? * MON *)`


---

### 1.5 DSG 配置

#### DSG AccessKey 生成

**步骤**:
1. 登录 DSG 管理界面: `https://10.2.*.*`
2. 导航: 系统管理 → API 用户管理
3. 创建或选择 API 用户
4. 点击"生成 AccessKey"
5. **立即保存 AccessKey**（只显示一次，无法再次查看）
6. 将 AccessKey 配置到 Lambda 环境变量 `DSG_API_KEY`

**AccessKey 格式**: 通常是 32-64 位字符串（示例: `a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6`）

**权限要求**:
- API 用户需要有"数据库连接管理"权限
- 能够查询数据库连接 (GET /api/v1/asset/db-connections)
- 能够更新数据库连接密码 (PUT /api/v1/asset/db-connections/{id})

#### DSG 数据库连接配置

**在 DSG 中预先配置的数据库连接示例**:

| 字段 | 值 | 说明 |
|-----|---|------|
| connectionName | `dsg-mysql-dev-1` | 连接名称（用于 Lambda 查询） |
| account | `dba_user` | 数据库账号名称 |
| password | `初始密码` | 将被 Lambda 更新 |
| host | `10.2.157.200` | 数据库主机地址 |
| port | `3306` | 数据库端口 |
| type | `MYSQL` | 数据库类型 |
| systemId | `1` | 系统 ID |
| dataOwnerDeptId | `1` | 数据所有者部门 ID |
| pwdStoreWay | `LOCAL` | 密码存储方式 |

**关键点**:
- ✅ `connectionName` 必须与 DynamoDB `rds-metadata` 表中的 `dsg_connection_name` 或 `rds_instance` 匹配
- ✅ `account` 必须与 Secrets Manager 中的 `account` 字段匹配（用于 `accountLike` 查询）
- ✅ 其他字段（systemId, dataOwnerDeptId, extInfo）在更新密码时必须保持不变

---

### 1.6 CloudWatch 监控配置（可选）

#### 日志组: /aws/lambda/rds-rotation-gateway

**配置**:
- Retention: 7 days (可调整)
- Subscription filters: 可配置发送到 SNS/Kinesis

#### CloudWatch Alarms（推荐配置）

**告警 1: Lambda 执行失败**

| 参数 | 值 |
|-----|---|
| Alarm name | `rds-rotation-gateway-errors` |
| Metric | Lambda > Errors |
| Function name | `rds-rotation-gateway` |
| Statistic | Sum |
| Period | 5 minutes |
| Threshold | >= 1 |
| Datapoints to alarm | 1 out of 1 |
| Action | SNS topic (需预先创建) |

**告警 2: Lambda 超时**

| 参数 | 值 |
|-----|---|
| Alarm name | `rds-rotation-gateway-timeouts` |
| Metric | Lambda > Duration |
| Function name | `rds-rotation-gateway` |
| Statistic | Maximum |
| Period | 5 minutes |
| Threshold | >= 840000 ms (14 分钟) |
| Action | SNS topic |


---

## 二、子账号（成员账号）详细配置

**需要在每个子账号（100+ 个）中执行以下配置**

**示例子账号 ID**: `286*********`  
**区域**: 与 DSG 账号相同（`cn-north-1` 或 `cn-northwest-1`）

---

### 2.1 IAM 角色配置

#### 角色: RDSRotationSyncRole

**完整配置参数**:

| 参数 | 值 |
|-----|---|
| Role name | `RDSRotationSyncRole` |
| Trusted entity | AWS account: 444********* |
| External ID | `rds-rotation-sync` |
| Description | 允许网关账号读取 RDS Secrets Manager 密文 |
| Max session duration | 1 hour (3600 seconds) |
| Path | / |

**ARN**: `arn:aws-cn:iam::286*********:role/RDSRotationSyncRole`  
（每个子账号的 ARN 不同，账号 ID 部分替换为实际子账号 ID）

**信任策略 (Trust Policy)**:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws-cn:iam::444*********:root"
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "sts:ExternalId": "rds-rotation-sync"
        }
      }
    }
  ]
}
```

**关键点**:
- ✅ Principal 使用 `arn:aws-cn` 分区（中国区）
- ✅ 账号 ID `444*********` 是 DSG 网关账号
- ✅ External ID `rds-rotation-sync` 必须与 Lambda 代码中的一致
- ✅ 所有子账号的角色名称必须统一为 `RDSRotationSyncRole`

**内联策略 (Inline Policy)**: `SecretsManagerReadPolicy`

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "SecretsManagerReadAccess",
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret"
      ],
      "Resource": "arn:aws-cn:secretsmanager:cn-north-1:286*********:secret:*"
    }
  ]
}
```

**权限范围说明**:
- 当前配置: 允许读取所有 Secret (`secret:*`)
- 推荐配置: 限制为特定前缀 (`secret:test/dsg/*` 或 `secret:rds/*`)
- 最小权限示例:
```json
{
  "Resource": [
    "arn:aws-cn:secretsmanager:cn-north-1:286*********:secret:test/dsg/*",
    "arn:aws-cn:secretsmanager:cn-north-1:286*********:secret:rds/*"
  ]
}
```


---

### 2.2 Secrets Manager 配置

#### Secret: test/dsg/mysql1（示例）

**完整配置参数**:

| 参数 | 值 |
|-----|---|
| Secret name | `test/dsg/mysql1` |
| Secret type | Other type of secret |
| Encryption key | aws/secretsmanager (默认) |
| Automatic rotation | Enabled (推荐) |
| Rotation schedule | 30 days |
| Rotation Lambda | 使用 AWS 托管或自定义 Lambda |

**ARN**: `arn:aws-cn:secretsmanager:cn-north-1:286*********:secret:test/dsg/mysql1-AbCdEf`  
（后缀 `-AbCdEf` 是 AWS 自动生成的 6 位随机字符）

**Secret 值结构** (JSON 格式):
```json
{
  "account": "dba_user",
  "password": "MySecurePassword123!",
  "host": "10.2.157.200",
  "port": 3306,
  "engine": "mysql",
  "dbname": "production",
  "username": "dba_user"
}
```

**字段说明**:
- `account` (必需): 数据库账号名称，用于 DSG API 的 `accountLike` 查询参数
- `password` (必需): 数据库密码，将被同步到 DSG
- `host` (可选): 数据库主机地址
- `port` (可选): 数据库端口
- `engine` (可选): 数据库引擎类型
- `dbname` (可选): 数据库名称
- `username` (可选): 数据库用户名（可与 account 相同）

**关键点**:
- ✅ **必须包含 `account` 字段**，代码会提取此字段用于 DSG 查询
- ✅ `account` 的值必须与 DSG 中数据库连接的 `account` 字段匹配
- ✅ 示例: DSG 中连接的 account 是 `dba_user`，Secret 中也必须是 `"account": "dba_user"`

**自动轮转配置**:

| 参数 | 值 |
|-----|---|
| Rotation enabled | Yes |
| Rotation schedule | 30 days |
| Rotation Lambda | `SecretsManagerRDSMySQLRotationSingleUser` (AWS 托管) |
| Rotation strategy | Single user |

**轮转 Lambda 权限**:
- 需要有权限连接到 RDS 实例
- 需要有权限更新 Secret 值
- 需要有 VPC 访问权限（如果 RDS 在 VPC 内）

---

### 2.3 RDS 实例配置（参考）

**示例 RDS 实例**: `dsg-mysql-dev-1`

| 参数 | 值 |
|-----|---|
| DB instance identifier | `dsg-mysql-dev-1` |
| Engine | MySQL 8.0.35 |
| Master username | `admin` |
| Endpoint | `dsg-mysql-dev-1.abc123.cn-north-1.rds.amazonaws.com.cn` |
| Port | 3306 |
| VPC | vpc-0abc123def456789 |
| Security group | sg-0abc123def456789 |

**安全组规则** (RDS 安全组):
- Inbound: MySQL (3306) ← Rotation Lambda 安全组
- Inbound: MySQL (3306) ← DSG 安全组或 IP

**关键点**:
- RDS 实例本身不需要特殊配置
- 确保 Rotation Lambda 能够访问 RDS
- 确保 DSG 能够访问 RDS（用于验证密码）

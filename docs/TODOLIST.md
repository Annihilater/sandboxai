# 默认空间名称标准化

## 问题描述
当前后端创建的默认空间名称为 "Default Space"，而 Python 客户端的 `Space` 模型要求 `name` 字段必须符合正则表达式 `^[a-z0-9]([-a-z0-9]*[a-z0-9])?$`。这导致在获取空间列表时出现验证错误。

## 临时解决方案
在 Python 客户端的 `list_spaces` 方法中添加了特殊处理，将 "Default Space" 转换为 "default" 以符合命名规则。

## 长期优化方案
1. 修改后端 `SpaceState` 结构体，添加 `IsDefault` 字段：
```go
type SpaceState struct {
    ID          string
    Name        string
    Description string
    CreatedAt   time.Time
    UpdatedAt   time.Time
    Metadata    map[string]interface{}
    Sandboxes   map[string]*SandboxState
    IsDefault   bool  // 新增字段
}
```

2. 修改默认空间创建逻辑：
```go
defaultSpace := &SpaceState{
    ID:        "default",
    Name:      "default",  // 使用小写
    IsDefault: true,       // 标记为默认空间
    CreatedAt: time.Now(),
    UpdatedAt: time.Now(),
    Sandboxes: make(map[string]*SandboxState),
}
```

3. 在 API 响应中添加 `is_default` 字段，让客户端知道这是默认空间

## 迁移策略
1. 添加新字段但不立即使用
2. 更新所有客户端代码以支持新字段
3. 在下一个主要版本中更改默认空间名称
4. 提供迁移指南，说明如何处理默认空间的变化

## 测试建议
1. 添加测试用例验证默认空间的行为
2. 测试空间列表功能
3. 测试空间创建和删除功能
4. 测试与默认空间相关的所有功能

## 优先级
低 - 当前临时解决方案可以正常工作，不影响客户端使用 
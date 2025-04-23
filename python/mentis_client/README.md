# Mentis Client

## 并发使用指南

### 基本概念

Mentis Client 支持并发执行多个任务，但需要注意以下几点：

1. **任务隔离**：每个并发任务使用独立的 action_id 来跟踪
2. **结果收集**：需要正确过滤和收集每个任务的结果
3. **资源管理**：及时处理任务结果

### 并发任务管理类

我们提供了一个 `ConcurrentTask` 类来简化并发任务的管理：

```python
class ConcurrentTask:
    def __init__(self, sandbox, task_id):
        self.sandbox = sandbox
        self.task_id = task_id
        self.action_id = None
    
    def execute(self, code):
        self.action_id = self.sandbox.run_ipython_cell(code)
        return self.action_id
    
    def collect_results(self, obs_queue, timeout=30):
        observations = []
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                obs = obs_queue.get(timeout=0.1)
                if obs.action_id == self.action_id:
                    observations.append(obs)
                    if obs.observation_type == "result":
                        return observations
            except queue.Empty:
                continue
        
        return observations
```

### 使用示例

```python
def run_concurrent_tasks():
    # 创建沙箱会话
    sandbox, obs_queue = sandbox_session
    
    # 创建并发任务
    tasks = [
        ConcurrentTask(sandbox, i)
        for i in range(3)
    ]
    
    # 执行所有任务
    for i, task in enumerate(tasks):
        code = f"import time\nprint('Task {i}')\ntime.sleep(1)"
        task.execute(code)
    
    # 等待所有任务完成
    time.sleep(3)
    
    # 收集结果
    results = {}
    for i, task in enumerate(tasks):
        observations = task.collect_results(obs_queue)
        stdout = ""
        for obs in observations:
            if obs.observation_type == "stream" and obs.stream == "stdout":
                stdout += obs.line
        results[i] = stdout
    
    return results
```

### 最佳实践

1. **任务管理**：
   - 为每个任务使用唯一的 task_id
   - 正确跟踪 action_id
   - 及时处理任务结果

2. **结果收集**：
   - 使用 action_id 正确过滤观察结果
   - 处理所有类型的观察结果（stream、result、error）
   - 设置适当的超时时间

3. **错误处理**：
   - 捕获并处理可能的异常
   - 记录详细的错误信息
   - 确保资源正确清理

4. **性能考虑**：
   - 控制并发任务的数量
   - 避免过多的资源占用
   - 考虑使用线程池或异步IO

### 注意事项

1. 确保服务器有足够的资源处理并发请求
2. 监控并发任务的内存和CPU使用情况
3. 实现适当的重试机制
4. 添加详细的日志记录
5. 考虑使用上下文管理器来管理资源

### 常见问题

1. **输出混淆**：
   - 问题：多个任务的输出混在一起
   - 解决：使用 action_id 正确过滤观察结果

2. **结果丢失**：
   - 问题：无法收到某些任务的结果
   - 解决：检查 WebSocket 连接状态，确保正确过滤观察结果

3. **超时问题**：
   - 问题：任务执行时间过长
   - 解决：设置合理的超时时间，实现超时处理机制 
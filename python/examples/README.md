# Mentis Client 示例说明

本目录包含 Mentis Client 的不同使用示例。根据不同的实现方式，运行要求有所不同：

## 启动 Mentis Runtime 服务器

在运行 `simple.py` 和 `langgraph_simple_connect.py` 之前，需要先启动 Mentis Runtime 服务器。服务器是使用 Go 语言实现的，可以通过以下两种方式启动：

### 方法一：编译后运行

1. 编译服务器可执行文件：
```bash
make build/sandboxaid
```

2. 运行服务器：
```bash
./bin/sandboxaid
```

可以通过 `--help` 查看帮助信息：
```bash
./bin/sandboxaid --help
```

### 方法二：直接运行 Go 代码

如果已安装 Go 环境，可以直接运行服务器代码：
```bash
go run ./go/mentisruntime/main.go
```

## 1. simple.py

这是一个基础的 Mentis Client 使用示例，需要先启动 Mentis Runtime 服务器才能运行。

运行步骤：
1. 确保 Mentis Runtime 服务器已启动并监听在 `http://localhost:5266`
2. 运行示例：
```bash
python simple.py
```

## 2. langgraph_simple_connect.py

这是一个使用 LangGraph 框架的示例，同样需要先启动 Mentis Runtime 服务器。

运行步骤：
1. 确保 Mentis Runtime 服务器已启动并监听在 `http://localhost:5266`
2. 运行示例：
```bash
python langgraph_simple_connect.py
```

## 3. langgraph_simple_embedded.py

这是一个使用嵌入式模式的示例，不需要手动启动 Mentis Runtime 服务器。该示例会自动启动和管理服务器进程。

运行步骤：
```bash
python langgraph_simple_embedded.py
```

## 实现机制说明

- `simple.py` 和 `langgraph_simple_connect.py` 使用 `MentisSandbox` 类，需要连接到外部运行的 Mentis Runtime 服务器。
- `langgraph_simple_embedded.py` 使用 `EmbeddedMentisSandbox` 类，它会自动启动和管理一个本地的 Mentis Runtime 服务器进程。当程序退出时，服务器会自动关闭。

## 依赖要求

所有示例都需要安装以下依赖：
```bash
pip install mentis-client langgraph langchain-core httpx
``` 
# mentis_client/embedded.py
import shutil
import subprocess
import json
import os
import atexit
import threading
import uuid
import logging
import time
import select
import fcntl
from typing import Optional

logger = logging.getLogger(__name__)

__process = None
__running = False
__base_url = None
__logging_thread = None
__scope_id = None


def _stream_to_logger(pipe):
    """
    辅助函数，在线程中运行。
    从子进程管道读取行并记录日志。
    """
    with pipe:
        for line in iter(pipe.readline, ""):
            # 移除尾部换行符以避免日志中出现双倍间距
            line = line.rstrip()
            if line:  # 避免空行
                logger.debug(f"服务器: {line}")


def start_server(port: int = 0, delete_on_shutdown: bool = True) -> None:
    """
    启动本地MentisRuntime服务器。
    
    Args:
        port: 服务器监听的端口，0表示自动选择空闲端口。
        delete_on_shutdown: 服务器关闭时是否删除所有管理的沙箱。
    
    Raises:
        RuntimeError: 如果启动服务器失败。
    """
    global __process
    global __base_url
    global __logging_thread
    global __running
    global __scope_id

    if __running:
        logger.info(f"嵌入式服务器已经在运行，基础URL: {__base_url}")
        return

    if not shutil.which("docker"):
        raise RuntimeError("系统中未找到docker。")

    # --- Corrected Runtime Path Logic --- 
    # Get the directory of the current file (embedded.py)
    current_dir = os.path.dirname(__file__)
    # Go up two levels to reach the 'python' directory's parent (project root)
    project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
    # Define the expected binary name
    binary_name = "sandboxaid"
    # Define potential paths
    runtime_paths = [
        # Path relative to project root
        os.path.join(project_root, "bin", binary_name),
        # Path assuming it's installed globally (in PATH)
        shutil.which(binary_name),
        # Fallback: Original incorrect path (just in case, but unlikely)
        os.path.join(os.path.dirname(__file__), "bin", binary_name), 
    ]
    
    runtime_path = None
    for path in runtime_paths:
        if path and os.path.isfile(path):
            logger.debug(f"Found runtime executable at: {path}")
            runtime_path = path
            break
    
    if not runtime_path:
        logger.error(f"Searched paths: {runtime_paths}")
        raise RuntimeError(f"未找到 {binary_name} 可执行文件。请确保它已编译并位于 {os.path.join(project_root, 'bin')} 或在系统 PATH 中。")
    # --- End Corrected Path Logic ---

    process_env = os.environ.copy()
    # 设置端口
    process_env["MENTIS_PORT"] = str(port)
    # 为此嵌入式实例设置作用域
    __scope_id = str(uuid.uuid4())
    process_env["MENTIS_SCOPE"] = __scope_id
    # 当服务器停止时，删除所有管理的沙箱
    process_env["MENTIS_DELETE_ON_SHUTDOWN"] = "true" if delete_on_shutdown else "false"
    
    # 日志中添加 runtime_path 和环境变量
    logger.info(f"启动 sandboxaid: {runtime_path}")
    logger.info(f"环境变量: MENTIS_PORT={port}, MENTIS_SCOPE={__scope_id}, MENTIS_DELETE_ON_SHUTDOWN={delete_on_shutdown}")

    # 在后台启动sandboxaid可执行文件
    __process = subprocess.Popen(
        [runtime_path], 
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=process_env,
        # 确保服务器不会同时接收到与Python程序相同的中断信号
        preexec_fn=os.setsid,
    )
    __running = True

    # 生成一个线程来读取stderr并记录其内容
    __logging_thread = threading.Thread(
        target=_stream_to_logger,
        args=(__process.stderr,),
        daemon=True,
    )
    __logging_thread.start()

    # 检查进程是否成功启动
    if __process.poll() is None:
        logger.info(f"Mentis Runtime服务器成功启动，PID: {__process.pid}")
        atexit.register(stop_server)
    else:
        # 如果进程立即退出，记录退出码
        exit_code = __process.returncode
        raise RuntimeError(f"启动sandboxaid失败，退出码: {exit_code}. 请检查DEBUG日志获取stderr输出.")

    if __process.stdout is None:
        raise RuntimeError("无法捕获stdout")

    # 增加读取超时机制，避免无限等待
    
    # 为stdout设置非阻塞模式
    fd = __process.stdout.fileno()
    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
    
    # 尝试读取自动选择的端口，带超时
    port_read_timeout = 5.0  # 5秒超时
    start_time = time.time()
    json_data = None
    lines = []
    
    logger.info("等待sandboxaid输出端口信息...")
    
    while time.time() - start_time < port_read_timeout:
        # 检查进程是否仍在运行
        if __process.poll() is not None:
            exit_code = __process.returncode
            # Raise error indicating unexpected exit, stderr should be in logs
            raise RuntimeError(f"sandboxaid意外退出，退出码: {exit_code}. 请检查DEBUG日志获取stderr输出.")
        
        # 检查是否有数据可读
        ready_to_read, _, _ = select.select([__process.stdout], [], [], 0.1)
        
        if ready_to_read:
            try:
                line = __process.stdout.readline()
                if not line:  # EOF
                    time.sleep(0.1)
                    continue
                    
                logger.debug(f"sandboxaid输出: {line.strip()}")
                lines.append(line.strip())
                
                # 尝试解析为JSON
                try:
                    json_data = json.loads(line.strip())
                    # 如果成功解析，退出循环
                    logger.debug(f"成功解析JSON数据: {json_data}")
                    break
                except json.JSONDecodeError:
                    # 继续读取下一行
                    pass
            except (IOError, OSError) as e:
                # 当前没有更多数据可读
                time.sleep(0.1)
        else:
            # 没有数据可读，稍等片刻
            time.sleep(0.1)
    
    # 如果未能解析JSON，使用备用方法检测端口
    if not json_data:
        logger.warning(f"超时等待sandboxaid输出JSON数据, 共收集了 {len(lines)} 行输出")
        for line in lines:
            logger.debug(f"收集的行: {line}")
        
        # 尝试通过检查进程列表来获取端口
        # 这是一个备用方案，检查sandboxaid是否在监听某个端口
        try:
            # 使用lsof检查进程打开的端口
            lsof_cmd = subprocess.run(
                ["lsof", "-Pan", "-p", str(__process.pid), "-i"], 
                capture_output=True, 
                text=True
            )
            
            if lsof_cmd.returncode == 0:
                # 寻找LISTEN状态的TCP端口
                for line in lsof_cmd.stdout.splitlines():
                    if "LISTEN" in line and "TCP" in line:
                        # 提取端口号，格式通常是 *:PORT 或 HOST:PORT
                        parts = line.split(":")
                        if len(parts) >= 2:
                            listen_port = parts[-1].split(" ")[0]
                            try:
                                port = int(listen_port)
                                logger.info(f"通过lsof检测到sandboxaid在端口 {port} 上监听")
                                __base_url = f"http://localhost:{port}"
                                logger.info(f"设置base_url为: {__base_url}")
                                return
                            except ValueError:
                                pass
            
            # 如果lsof失败或没有找到端口，尝试使用默认端口5266
            logger.warning("无法检测到sandboxaid监听的端口，尝试使用默认端口5266")
            __base_url = "http://localhost:5266"
            
        except Exception as e:
            logger.error(f"检测sandboxaid端口时出错: {e}")
            logger.warning("使用默认端口5266")
            __base_url = "http://localhost:5266"
        
        return
    
    # 处理找到的JSON数据
    try:
        port = json_data.get("port")
        if port:
            __base_url = f"http://localhost:{port}"
            logger.info(f"Mentis Runtime服务器监听在: {__base_url}")
        else:
            logger.warning(f"JSON数据中没有port字段: {json_data}")
            # 使用默认端口
            __base_url = "http://localhost:5266"
            logger.info(f"使用默认端口: {__base_url}")
    except Exception as e:
        logger.error(f"处理JSON数据时出错: {e}")
        # 在出错的情况下也使用默认端口
        __base_url = "http://localhost:5266"
        logger.info(f"使用默认端口: {__base_url}")


def stop_server() -> None:
    """
    停止本地MentisRuntime服务器。
    """
    global __process
    global __running
    global __logging_thread
    
    if __process:
        try:
            logger.info("正在终止嵌入式服务器")
            __process.terminate()
            __running = False
            logger.info("等待嵌入式服务器停止")
            __process.wait(timeout=30)
            logger.info("嵌入式服务器已停止")
            if __logging_thread:
                # 显式等待日志线程也停止
                # 这是必要的，以确保所有日志都被写入
                # 日志线程以守护模式运行，因为关闭是在"atexit"触发的，而"atexit"只在所有线程停止后才触发
                logger.info("等待日志线程停止")
                __logging_thread.join(timeout=10)
                logger.debug("嵌入式日志线程已停止")
        except OSError:
            pass  # 进程可能已经终止
    __process = None


def is_running() -> bool:
    """
    检查嵌入式服务器是否正在运行。
    
    Returns:
        bool: 如果服务器正在运行，则为True，否则为False。
    """
    global __running
    return __running


def get_base_url() -> Optional[str]:
    """
    获取嵌入式服务器的基础URL。
    
    Returns:
        Optional[str]: 服务器的基础URL，如果服务器未运行则为None。
    """
    global __base_url
    return __base_url


def get_scope_id() -> Optional[str]:
    """
    获取嵌入式服务器的作用域ID。
    
    Returns:
        Optional[str]: 服务器的作用域ID，如果服务器未运行则为None。
    """
    global __scope_id
    return __scope_id


class EmbeddedMentisSandbox:
    """
    使用嵌入式MentisRuntime服务器的沙箱客户端。
    
    这个类提供了一个简单的接口，用于启动嵌入式服务器并创建与之连接的沙箱客户端。
    它主要用于简化本地开发和测试场景。
    
    可以通过传递 observation_queue 或回调函数给构造函数来接收观察结果。
    """
    
    def __init__(self, auto_start: bool = True, port: int = 0, delete_on_shutdown: bool = True, **kwargs):
        """
        初始化嵌入式沙箱客户端。
        
        Args:
            auto_start: 是否自动启动嵌入式服务器。
            port: 服务器监听的端口，0表示自动选择空闲端口。
            delete_on_shutdown: 服务器关闭时是否删除所有管理的沙箱。
            **kwargs: 传递给 MentisSandbox.create 的额外参数 (例如 observation_queue, on_observation_callback)。
        """
        if auto_start and not is_running():
            start_server(port=port, delete_on_shutdown=delete_on_shutdown)
            # 等待服务器启动
            start_time = time.time()
            while not get_base_url() and time.time() - start_time < 30:
                time.sleep(0.1)
            if not get_base_url():
                raise RuntimeError("嵌入式服务器启动超时")
        
        if not is_running():
            raise RuntimeError("嵌入式服务器未运行")
        
        self.base_url = get_base_url()
        
        # 导入这里以避免循环导入
        from .client import MentisSandbox
        
        # 创建一个连接到嵌入式服务器的沙箱客户端，并传递kwargs
        # Now passes kwargs like observation_queue through
        self.sandbox = MentisSandbox.create(base_url=self.base_url, **kwargs) 
    
    def __enter__(self):
        # 返回底层的 MentisSandbox 实例
        return self.sandbox
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # 删除沙箱，但保持服务器运行
        # 服务器将在Python程序退出时通过atexit处理程序关闭
        try:
            # Ensure sandbox instance exists before trying to delete
            if hasattr(self, 'sandbox') and self.sandbox:
                 self.sandbox.delete() # Use delete method which handles closing client
            else:
                 logger.warning("Sandbox instance not found during exit, cannot delete.")
        except Exception as e:
            logger.warning(f"退出时删除沙箱失败: {e}", exc_info=True) # Add exc_info
        return False  # 不抑制异常
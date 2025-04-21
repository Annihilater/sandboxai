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

    # 查找mentis_runtime可执行文件
    runtime_paths = [
        # 从包含的二进制文件中查找
        os.path.join(os.path.dirname(__file__), "bin", "mentis_runtime"),
        # 从PATH环境变量中查找
        shutil.which("mentis_runtime"),
    ]
    
    runtime_path = None
    for path in runtime_paths:
        if path and os.path.isfile(path):
            runtime_path = path
            break
    
    if not runtime_path:
        raise RuntimeError("未找到mentis_runtime可执行文件。请确保它已安装或包含在库中。")

    process_env = os.environ.copy()
    # 设置端口
    process_env["MENTIS_PORT"] = str(port)
    # 为此嵌入式实例设置作用域
    __scope_id = str(uuid.uuid4())
    process_env["MENTIS_SCOPE"] = __scope_id
    # 当服务器停止时，删除所有管理的沙箱
    process_env["MENTIS_DELETE_ON_SHUTDOWN"] = "true" if delete_on_shutdown else "false"

    # 在后台启动mentis_runtime可执行文件
    __process = subprocess.Popen(
        [runtime_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=process_env,
        # 确保服务器不会同时接收到与Python程序相同的中断信号
        # 这对于在服务器停止接受新请求之前处理所有沙箱删除请求很重要
        # 参见stop_server()函数中的关闭流程（通过atexit注册）
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
        # 注意：Python __exit__函数应该在atexit函数运行之前完成
        # 这允许使用`with:`语句启动的沙箱通过向嵌入式服务器发出DELETE请求来正确清理自己
        atexit.register(stop_server)
    else:
        raise RuntimeError("启动mentis_runtime失败")

    if __process.stdout is None:
        raise RuntimeError("无法捕获stdout")

    # 读取自动选择的端口
    first_line = __process.stdout.readline().strip()
    try:
        server_info = json.loads(first_line)
        port = server_info.get("port")
        __base_url = f"http://localhost:{port}"
        logger.info(f"Mentis Runtime服务器监听在: {__base_url}")
    except json.JSONDecodeError as e:
        __process.terminate()
        raise json.JSONDecodeError(
            f"无法将第一行解码为JSON: {first_line}", e.doc, e.pos
        ) from e


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
    """
    
    def __init__(self, auto_start: bool = True, port: int = 0, delete_on_shutdown: bool = True):
        """
        初始化嵌入式沙箱客户端。
        
        Args:
            auto_start: 是否自动启动嵌入式服务器。
            port: 服务器监听的端口，0表示自动选择空闲端口。
            delete_on_shutdown: 服务器关闭时是否删除所有管理的沙箱。
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
        
        # 创建一个连接到嵌入式服务器的沙箱客户端
        self.sandbox = MentisSandbox.create(base_url=self.base_url)
    
    def __enter__(self):
        return self.sandbox
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # 删除沙箱，但保持服务器运行
        # 服务器将在Python程序退出时通过atexit处理程序关闭
        try:
            self.sandbox.delete()
        except Exception as e:
            logger.warning(f"退出时删除沙箱失败: {e}")
        return False  # 不抑制异常
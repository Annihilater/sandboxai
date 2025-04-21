# filename: python/examples/simple.py
import logging
import os
from mentis_client import MentisSandbox, MentisSandboxError

# 配置日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("mentis-example-simple")

# 从环境变量获取 Runtime URL，如果未设置则使用默认值
BASE_URL = os.environ.get("MENTIS_RUNTIME_URL", "http://127.0.0.1:5266")

def main():
    logger.info(f"连接到 Mentis Runtime: {BASE_URL}")
    
    try:
        # 使用简化的 API 创建 Sandbox 并执行代码
        with MentisSandbox.create(base_url=BASE_URL) as sandbox:
            # 简单的打印语句
            result1 = sandbox.run_code("print('Hello world!')")
            logger.info(f"执行结果1: {result1}")
            
            # 执行计算并返回结果
            result2 = sandbox.run_code("5 * 8")
            logger.info(f"执行结果2: {result2}")
            
            # 多行代码示例
            multi_line_code = """
            import numpy as np
            
            # 创建一个数组
            arr = np.array([1, 2, 3, 4, 5])
            
            # 计算平均值
            mean = np.mean(arr)
            print(f'数组: {arr}')
            print(f'平均值: {mean}')
            
            # 返回结果
            mean
            """
            try:
                result3 = sandbox.run_code(multi_line_code)
                logger.info(f"执行结果3: {result3}")
            except MentisSandboxError as e:
                # numpy可能未安装，捕获可能的错误
                logger.warning(f"执行多行代码时出错: {e}")
            
    except MentisSandboxError as e:
        logger.error(f"Sandbox 操作失败: {e}")

if __name__ == "__main__":
    main()
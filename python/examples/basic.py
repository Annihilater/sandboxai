# filename: python/examples/basic_rewritten.py
import logging
import os
import time
from queue import Queue, Empty
from typing import List, Optional, Union, cast

# 从我们当前的 client 库导入
from mentis_client import MentisSandbox, MentisSandboxError
from mentis_client.models import (
    BaseObservation,
    IPythonResultObservation,
    IPythonOutputObservationPart,
    CmdEndObservation,
    CmdOutputObservationPart,
    ErrorObservation
)

# 配置日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("mentis-example-basic")

# --- 配置 ---
# 从环境变量获取 Runtime URL，如果未设置则使用默认值
# 确保这里的端口号 (5266) 与你启动 Go 服务时使用的端口一致
BASE_URL = os.environ.get("MENTIS_RUNTIME_URL", "http://127.0.0.1:5266")
OBSERVATION_TIMEOUT_SECONDS = 30.0 # 等待结果的超时时间

# --- 简化的结果收集辅助函数 ---
def collect_results(
    q: Queue,
    action_id: str,
    stop_observation_type: str,
    timeout: float = OBSERVATION_TIMEOUT_SECONDS
) -> List[BaseObservation]:
    """
    从队列中收集与指定 action_id 相关的观测数据，
    直到收到指定类型的结束观测或超时。
    """
    observations = []
    start_time = time.time()
    logger.info(f"Collecting observations for action_id: {action_id} (timeout={timeout}s)")
    while time.time() - start_time < timeout:
        try:
            # 短暂等待，避免CPU空转
            obs: BaseObservation = q.get(timeout=0.2)
            logger.debug(f"Got observation: Type={obs.observation_type}, ActionID={obs.action_id}")

            # 只收集与目标 action_id 匹配的观测数据
            if obs.action_id == action_id:
                observations.append(obs)
                # 检查是否是我们要等待的结束信号
                if obs.observation_type == stop_observation_type:
                    logger.info(f"Stop condition met ({stop_observation_type}) for action_id: {action_id}")
                    return observations
                # 如果是错误观测，也提前返回
                if obs.observation_type == "ErrorObservation":
                    logger.warning(f"Received ErrorObservation for action_id: {action_id}")
                    return observations # Return immediately on error observation
            elif obs.action_id:
                 logger.debug(f"Ignoring observation for different action_id: {obs.action_id}")
            else:
                 logger.debug(f"Ignoring observation without action_id: {obs.observation_type}")

        except Empty:
            # 队列为空，继续等待
            continue
        except Exception as e:
            logger.error(f"Error getting observation from queue: {e}", exc_info=True)
            # Or re-raise depending on desired handling
            break # Exit loop on other errors

    # 如果循环结束仍未满足停止条件，则超时
    collected_types = [o.observation_type for o in observations]
    logger.error(f"Timeout ({timeout}s) waiting for {stop_observation_type} for action {action_id}. Collected: {collected_types}")
    # 返回已收集到的数据，让调用者处理超时
    return observations


# --- 主逻辑 ---
def main():
    logger.info(f"Attempting to connect to Mentis Runtime at: {BASE_URL}")
    obs_queue: Queue = Queue() # 用于接收观测数据的队列

    try:
        # 1. 创建 Sandbox (使用 with 语句确保资源释放)
        # 注意：这里不再有 embedded=True 选项，需要单独运行 Go 服务
        with MentisSandbox.create(
            base_url=BASE_URL,
            observation_queue=obs_queue, # 将队列传递给客户端
            # 可以添加其他回调，例如 on_error_callback
        ) as box:
            logger.info(f"Sandbox created successfully: {box.sandbox_id}")

            # 2. 连接 WebSocket 流
            try:
                logger.info("Connecting to WebSocket stream...")
                box.connect_stream(timeout=10.0) # 等待连接，设置超时
                if box.is_stream_connected():
                    logger.info("WebSocket stream connected.")
                else:
                     logger.error("Failed to connect WebSocket stream after timeout.")
                     return # 无法继续
            except Exception as conn_err:
                logger.error(f"Error connecting WebSocket stream: {conn_err}", exc_info=True)
                return # 无法继续

            # 3. 执行 IPython 命令
            code_to_run = "print('Hello from Mentis Client!')\nresult = 5*8\nresult"
            logger.info(f"Running IPython cell: \n{code_to_run}")
            try:
                action_id = box.run_ipython_cell(code=code_to_run)
                logger.info(f"IPython action initiated with action_id: {action_id}")

                # 4. 收集结果 (等待 IPythonResultObservation)
                ipython_results = collect_results(obs_queue, action_id, "IPythonResultObservation")

                # 5. 处理和打印结果
                final_status = "Unknown"
                final_output = ""
                final_error = None

                for obs in ipython_results:
                    if obs.observation_type == "IPythonOutputObservationPart":
                         # 需要强制类型转换来访问子类特有字段
                        output_part = cast(IPythonOutputObservationPart, obs)
                        if output_part.stream == "stdout":
                             final_output += output_part.data
                        elif output_part.stream == "stderr":
                             final_output += f"[STDERR] {output_part.data}"
                        # 可以根据需要处理 execute_result, display_data 等
                        elif output_part.stream == "execute_result" and isinstance(output_part.data, dict):
                             # 尝试提取 text/plain 输出
                             plain_text = output_part.data.get("text/plain", "")
                             if plain_text:
                                 final_output += f"Out: {plain_text}\n"
                    elif obs.observation_type == "IPythonResultObservation":
                         result_obs = cast(IPythonResultObservation, obs)
                         final_status = result_obs.status
                         if result_obs.status == 'error':
                              final_error = f"{result_obs.error_name}: {result_obs.error_value}"
                              # 可以选择性地加入 traceback
                              # if result_obs.traceback:
                              #    final_error += "\n" + "\n".join(result_obs.traceback)
                    elif obs.observation_type == "ErrorObservation":
                        error_obs = cast(ErrorObservation, obs)
                        final_status = "Error"
                        final_error = error_obs.message

                logger.info("-------- IPython Execution Result --------")
                logger.info(f"Action ID: {action_id}")
                logger.info(f"Final Status: {final_status}")
                if final_output:
                     logger.info(f"Output:\n{final_output.strip()}")
                if final_error:
                     logger.error(f"Error: {final_error}")
                logger.info("-----------------------------------------")

            except APIError as api_err:
                 logger.error(f"API error running IPython cell: {api_err}")
            except MentisSandboxError as general_err:
                 logger.error(f"Sandbox error running IPython cell: {general_err}")

            # 可以在这里添加运行 Shell 命令的示例...
            # command_to_run = "ls -l /work"
            # logger.info(f"Running Shell command: {command_to_run}")
            # shell_action_id = box.run_shell_command(command=command_to_run)
            # shell_results = collect_results(obs_queue, shell_action_id, "CmdEndObservation")
            # ... 处理 shell_results ...

    except MentisSandboxError as e:
        logger.error(f"Failed to create or interact with sandbox: {e}", exc_info=True)

if __name__ == "__main__":
    main()

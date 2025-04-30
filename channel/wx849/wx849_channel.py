import asyncio
import os
import json
import time
import threading
import io
import sys
import traceback  # 添加traceback模块导入
import xml.etree.ElementTree as ET  # 在顶部添加ET导入
from typing import Dict, Any

import requests
from bridge.context import Context, ContextType  # 确保导入Context类
from bridge.reply import Reply, ReplyType
from channel.chat_channel import ChatChannel
from channel.chat_message import ChatMessage
from channel.wx849.wx849_message import WX849Message  # 改为从wx849_message导入WX849Message
from common.expired_dict import ExpiredDict
from common.log import logger
from common.singleton import singleton
from common.time_check import time_checker
from common.utils import remove_markdown_symbol
from config import conf, get_appdata_dir, save_config

# 增大日志行长度限制，以便完整显示XML内容
try:
    import logging
    # 尝试设置日志格式化器的最大长度限制
    for handler in logging.getLogger().handlers:
        if hasattr(handler, 'formatter'):
            handler.formatter._fmt = handler.formatter._fmt.replace('%(message)s', '%(message).10000s')
    logger.info("[WX849] 已增大日志输出长度限制")
except Exception as e:
    logger.warning(f"[WX849] 设置日志长度限制失败: {e}")

# 添加 wx849 目录到 sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
# 修改路径查找逻辑，确保能找到正确的 lib/wx849 目录
# 先尝试当前项目中的相对路径
lib_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(current_dir))), "lib", "wx849")
if not os.path.exists(lib_dir):
    # 如果路径不存在，尝试使用绝对路径 /root/dow-849/lib/wx849
    lib_dir = os.path.join("/root", "dow-849", "lib", "wx849")

# 打印路径信息以便调试
logger.info(f"WechatAPI 模块搜索路径: {lib_dir}")

if os.path.exists(lib_dir):
    if lib_dir not in sys.path:
        sys.path.append(lib_dir)
    # 直接添加 WechatAPI 目录到路径
    wechat_api_dir = os.path.join(lib_dir, "WechatAPI")
    if os.path.exists(wechat_api_dir) and wechat_api_dir not in sys.path:
        sys.path.append(wechat_api_dir)
    logger.info(f"已添加 WechatAPI 模块路径: {lib_dir}")
    logger.info(f"Python 搜索路径: {sys.path}")
else:
    logger.error(f"WechatAPI 模块路径不存在: {lib_dir}")

# 导入 WechatAPI 客户端
try:
    # 使用不同的导入方式尝试
    try:
        # 尝试方式1：直接导入
        import WechatAPI
        from WechatAPI import WechatAPIClient
        logger.info("成功导入 WechatAPI 模块（方式1）")
    except ImportError:
        # 尝试方式2：从相对路径导入
        sys.path.append(os.path.dirname(lib_dir))
        from wx849.WechatAPI import WechatAPIClient
        import wx849.WechatAPI as WechatAPI
        logger.info("成功导入 WechatAPI 模块（方式2）")
    
    # 设置 WechatAPI 的 loguru 日志级别（关键修改）
    try:
        from loguru import logger as api_logger
        import logging
        
        # 移除所有现有处理器
        api_logger.remove()
        
        # 获取配置的日志级别，默认为 ERROR 以减少输出
        log_level = conf().get("log_level", "ERROR")
        
        # 添加新的处理器，仅输出 ERROR 级别以上的日志
        api_logger.add(sys.stderr, level=log_level)
        logger.info(f"已设置 WechatAPI 日志级别为: {log_level}")
    except Exception as e:
        logger.error(f"设置 WechatAPI 日志级别时出错: {e}")
except Exception as e:
    logger.error(f"导入 WechatAPI 模块失败: {e}")
    # 打印更详细的调试信息
    logger.error(f"当前Python路径: {sys.path}")
    
    # 检查目录内容
    if os.path.exists(lib_dir):
        logger.info(f"lib_dir 目录内容: {os.listdir(lib_dir)}")
        wechat_api_dir = os.path.join(lib_dir, "WechatAPI")
        if os.path.exists(wechat_api_dir):
            logger.info(f"WechatAPI 目录内容: {os.listdir(wechat_api_dir)}")
    
    raise ImportError(f"无法导入 WechatAPI 模块，请确保 wx849 目录已正确配置: {e}")

# 添加 ContextType.PAT 类型（如果不存在）
if not hasattr(ContextType, 'PAT'):
    setattr(ContextType, 'PAT', 'PAT')
if not hasattr(ContextType, 'QUOTE'):
    setattr(ContextType, 'QUOTE', 'QUOTE')
# 添加 ContextType.UNKNOWN 类型（如果不存在）
if not hasattr(ContextType, 'UNKNOWN'):
    setattr(ContextType, 'UNKNOWN', 'UNKNOWN')
# 添加 ContextType.XML 类型（如果不存在）
if not hasattr(ContextType, 'XML'):
    setattr(ContextType, 'XML', 'XML')
    logger.info("[WX849] 已添加 ContextType.XML 类型")
# 添加其他可能使用的ContextType类型
if not hasattr(ContextType, 'LINK'):
    setattr(ContextType, 'LINK', 'LINK')
    logger.info("[WX849] 已添加 ContextType.LINK 类型")
if not hasattr(ContextType, 'FILE'):
    setattr(ContextType, 'FILE', 'FILE')
    logger.info("[WX849] 已添加 ContextType.FILE 类型")
if not hasattr(ContextType, 'MINIAPP'):
    setattr(ContextType, 'MINIAPP', 'MINIAPP')
    logger.info("[WX849] 已添加 ContextType.MINIAPP 类型")
if not hasattr(ContextType, 'SYSTEM'):
    setattr(ContextType, 'SYSTEM', 'SYSTEM')
    logger.info("[WX849] 已添加 ContextType.SYSTEM 类型")
if not hasattr(ContextType, 'VIDEO'):
    setattr(ContextType, 'VIDEO', 'VIDEO')
    logger.info("[WX849] 已添加 ContextType.VIDEO 类型")

def _check(func):
    def wrapper(self, cmsg: ChatMessage):
        msgId = cmsg.msg_id
        
        # 如果消息ID为空，生成一个唯一ID
        if not msgId:
            msgId = f"msg_{int(time.time())}_{hash(str(cmsg.msg))}"
            logger.debug(f"[WX849] _check: 为空消息ID生成唯一ID: {msgId}")
        
        # 检查消息是否已经处理过
        if msgId in self.received_msgs:
            logger.debug(f"[WX849] 消息 {msgId} 已处理过，忽略")
            return
        
        # 标记消息为已处理
        self.received_msgs[msgId] = True
        
        # 检查消息时间是否过期
        create_time = cmsg.create_time  # 消息时间戳
        current_time = int(time.time())
        
        # 设置超时时间为60秒
        timeout = 60
        if int(create_time) < current_time - timeout:
            logger.debug(f"[WX849] 历史消息 {msgId} 已跳过，时间差: {current_time - int(create_time)}秒")
            return
        
        # 处理消息
        return func(self, cmsg)
    return wrapper

@singleton
class WX849Channel(ChatChannel):
    """
    wx849 channel - 独立通道实现
    """
    NOT_SUPPORT_REPLYTYPE = []

    def __init__(self):
        super().__init__()
        self.received_msgs = ExpiredDict(conf().get("expires_in_seconds", 3600))
        self.bot = None
        self.user_id = None
        self.name = None
        self.wxid = None
        self.is_running = False
        self.is_logged_in = False
        self.group_name_cache = {}

    async def _initialize_bot(self):
        """初始化 bot"""
        logger.info("[WX849] 正在初始化 bot...")
        
        # 读取协议版本设置
        protocol_version = conf().get("wx849_protocol_version", "849")
        logger.info(f"使用协议版本: {protocol_version}")
        
        api_host = conf().get("wx849_api_host", "127.0.0.1")
        api_port = conf().get("wx849_api_port", 9000)
        
        # 设置API路径前缀，根据协议版本区分
        if protocol_version == "855" or protocol_version == "ipad":
            api_path_prefix = "/api"
            logger.info(f"使用API路径前缀: {api_path_prefix} (适用于{protocol_version}协议)")
        else:
            api_path_prefix = "/VXAPI"
            logger.info(f"使用API路径前缀: {api_path_prefix} (适用于849协议)")
        
        # 实例化 WechatAPI 客户端
        if protocol_version == "855":
            # 855版本使用Client2
            try:
                from WechatAPI.Client2 import WechatAPIClient as WechatAPIClient2
                self.bot = WechatAPIClient2(api_host, api_port)
                # 设置API路径前缀
                if hasattr(self.bot, "set_api_path_prefix"):
                    self.bot.set_api_path_prefix(api_path_prefix)
                logger.info("成功加载855协议客户端")
            except Exception as e:
                logger.error(f"加载855协议客户端失败: {e}")
                logger.warning("回退使用默认客户端")
                self.bot = WechatAPI.WechatAPIClient(api_host, api_port)
                # 设置API路径前缀
                if hasattr(self.bot, "set_api_path_prefix"):
                    self.bot.set_api_path_prefix(api_path_prefix)
        elif protocol_version == "ipad":
            # iPad版本使用Client3
            try:
                from WechatAPI.Client3 import WechatAPIClient as WechatAPIClient3
                self.bot = WechatAPIClient3(api_host, api_port)
                # 设置API路径前缀
                if hasattr(self.bot, "set_api_path_prefix"):
                    self.bot.set_api_path_prefix(api_path_prefix)
                logger.info("成功加载iPad协议客户端")
            except Exception as e:
                logger.error(f"加载iPad协议客户端失败: {e}")
                logger.warning("回退使用默认客户端")
                self.bot = WechatAPI.WechatAPIClient(api_host, api_port)
                # 设置API路径前缀
                if hasattr(self.bot, "set_api_path_prefix"):
                    self.bot.set_api_path_prefix(api_path_prefix)
        else:
            # 849版本使用默认Client
            self.bot = WechatAPI.WechatAPIClient(api_host, api_port)
            # 设置API路径前缀
            if hasattr(self.bot, "set_api_path_prefix"):
                self.bot.set_api_path_prefix(api_path_prefix)
            logger.info("使用849协议客户端")
            
        # 设置bot的ignore_protection属性为True，强制忽略所有风控保护
        if hasattr(self.bot, "ignore_protection"):
            self.bot.ignore_protection = True
            logger.info("[WX849] 已设置忽略风控保护")

        # 等待 WechatAPI 服务启动
        time_out = 30
        
        # 使用不同的方法检查服务是否可用，包括尝试直接访问API端点
        logger.info(f"尝试连接到 WechatAPI 服务 (地址: {api_host}:{api_port}{api_path_prefix})")
        
        is_connected = False
        while not is_connected and time_out > 0:
            try:
                # 首先尝试使用bot对象的is_running方法
                if await self.bot.is_running():
                    is_connected = True
                    logger.info("[WX849] API服务已通过is_running方法确认可用")
                    break
                
                # 如果bot对象的方法失败，尝试直接发送HTTP请求检查服务是否可用
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    try:
                        # 尝试访问登录接口
                        url = f"http://{api_host}:{api_port}{api_path_prefix}/Login/GetQR"
                        logger.debug(f"尝试连接: {url}")
                        async with session.get(url, timeout=5) as response:
                            if response.status in [200, 401, 403, 404]:  # 任何HTTP响应都表示服务在运行
                                is_connected = True
                                logger.info("通过HTTP请求确认服务可用")
                                break
                    except:
                        # 如果特定路径失败，尝试访问根路径
                        url = f"http://{api_host}:{api_port}/"
                        logger.debug(f"尝试连接: {url}")
                        async with session.get(url, timeout=5) as response:
                            if response.status in [200, 401, 403, 404]:
                                is_connected = True
                                logger.info("通过根路径确认服务可用")
                                break
            except Exception as e:
                logger.debug(f"连接尝试失败: {e}")
            
            logger.info("等待 WechatAPI 启动中")
            await asyncio.sleep(2)
            time_out -= 2

        if not is_connected:
            logger.error("WechatAPI 服务启动超时")
            return False
            
        # 添加：先尝试二次登录，如果失败再进行二维码登录
        try:
            # 检查配置中是否存在已保存的wxid和device_id
            saved_wxid = conf().get("wx849_wxid", "")
            saved_device_id = conf().get("wx849_device_id", "")
            device_name = conf().get("wx849_device_name", "DoW微信机器人")
            
            if saved_wxid:
                logger.info(f"[WX849] 尝试获取缓存登录信息 (Wxid: {saved_wxid})")
                
                # 尝试获取缓存信息
                try:
                    get_cached_info = await self.bot.get_cached_info(saved_wxid)
                    logger.debug(f"[WX849] 获取缓存登录信息结果: {get_cached_info}")
                    
                    if get_cached_info:
                        # 尝试二次登录
                        logger.info("[WX849] 尝试二次登录")
                        twice_login_result = await self.bot.twice_login(saved_wxid)
                        logger.info(f"[WX849] 二次登录结果: {twice_login_result}")
                        
                        if twice_login_result:
                            logger.info("[WX849] 二次登录成功")
                            # 获取用户信息
                            profile = await self.bot.get_profile()
                            if profile and isinstance(profile, dict):
                                user_info = profile.get("userInfo", {})
                                self.wxid = saved_wxid
                                # 根据返回结构提取昵称
                                if "NickName" in user_info:
                                    if isinstance(user_info["NickName"], dict) and "string" in user_info["NickName"]:
                                        self.name = user_info["NickName"]["string"]
                                    else:
                                        self.name = str(user_info["NickName"])
                                self.user_id = self.wxid
                                logger.info(f"[WX849] 获取到用户信息: user_id: {self.user_id}, nickname: {self.name}")
                                self.is_logged_in = True
                                return True
                        else:
                            logger.error("[WX849] 二次登录失败，尝试唤醒登录")
                            # 尝试唤醒登录
                            try:
                                # 参照示例代码中的唤醒登录方式，使用异步HTTP请求直接调用API
                                async with aiohttp.ClientSession() as session:
                                    # 获取API配置
                                    api_host = conf().get("wx849_api_host", "127.0.0.1")
                                    api_port = conf().get("wx849_api_port", 9000)
                                    
                                    # 根据协议版本选择API路径
                                    protocol_version = conf().get("wx849_protocol_version", "849")
                                    if protocol_version == "855":
                                        api_base = "/api"
                                    elif protocol_version == "ipad":
                                        api_base = "/api"
                                    else:
                                        api_base = "/VXAPI"
                                    
                                    api_url = f'http://{api_host}:{api_port}{api_base}/Login/Awaken'
                                    
                                    # 准备参数
                                    json_param = {
                                        "OS": device_name,
                                        "Proxy": {
                                            "ProxyIp": "",
                                            "ProxyPassword": "",
                                            "ProxyUser": ""
                                        },
                                        "Url": "",
                                        "Wxid": saved_wxid
                                    }
                                    
                                    logger.debug(f"[WX849] 发送唤醒登录请求到 {api_url} 参数: {json_param}")
                                    
                                    try:
                                        # 发送请求
                                        response = await session.post(api_url, json=json_param)
                                        
                                        # 检查响应状态码
                                        if response.status != 200:
                                            logger.error(f"[WX849] 唤醒登录请求失败，状态码: {response.status}")
                                            raise Exception(f"服务器返回状态码 {response.status}")
                                        
                                        # 解析响应内容
                                        json_resp = await response.json()
                                        logger.debug(f"[WX849] 唤醒登录响应: {json_resp}")
                                        
                                        # 检查是否成功
                                        if json_resp and json_resp.get("Success"):
                                            # 尝试获取 UUID
                                            data = json_resp.get("Data", {})
                                            qr_response = data.get("QrCodeResponse", {}) if data else {}
                                            uuid = qr_response.get("Uuid", "") if qr_response else ""
                                            
                                            if uuid:
                                                logger.info(f"[WX849] 唤醒登录成功，获取到登录uuid: {uuid}")
                                                
                                                # 等待登录完成
                                                login_timeout = 120
                                                while login_timeout > 0:
                                                    try:
                                                        # 检查登录状态
                                                        login_success, login_result = await self.bot.check_login_uuid(uuid, device_id=saved_device_id)
                                                        
                                                        if login_success:
                                                            logger.info("[WX849] 唤醒登录完成，已获取登录信息")
                                                            
                                                            # 设置用户信息
                                                            if isinstance(login_result, dict) and login_result.get("acctSectResp"):
                                                                self.wxid = login_result.get("acctSectResp").get("userName", saved_wxid)
                                                                self.name = login_result.get("acctSectResp").get("nickName", "")
                                                                self.user_id = self.wxid
                                                                
                                                                # 保存wxid和device_id到配置
                                                                config = conf()
                                                                config.set("wx849_wxid", self.wxid)
                                                                if saved_device_id:
                                                                    config.set("wx849_device_id", saved_device_id)
                                                                config.set("wx849_device_name", device_name)
                                                                config.save_user_datas()
                                                                # 同时将配置保存到配置文件
                                                                save_config()
                                                                logger.info(f"[WX849] 已保存登录信息到配置: wxid={self.wxid}, device_id={saved_device_id}, device_name={device_name}")
                                                                
                                                                logger.info(f"[WX849] 登录信息: user_id: {self.user_id}, nickname: {self.name}")
                                                                self.is_logged_in = True
                                                                
                                                                return True
                                                    except Exception as e:
                                                        logger.error(f"[WX849] 检查唤醒登录状态出错: {e}")
                                                    
                                                    # 等待2秒后再次检查
                                                    await asyncio.sleep(2)
                                                    login_timeout -= 2
                                                    logger.info(f"[WX849] 等待唤醒登录完成，剩余 {login_timeout} 秒...")
                                                
                                                logger.error("[WX849] 唤醒登录超时或失败")
                                            else:
                                                logger.error("[WX849] 唤醒登录响应中没有有效的UUID")
                                        else:
                                            # 如果请求不成功，获取错误信息
                                            error_msg = json_resp.get("Message", "未知错误") if json_resp else "未知错误"
                                            logger.error(f"[WX849] 唤醒登录失败: {error_msg}")
                                            raise Exception(error_msg)
                                    except Exception as e:
                                        logger.error(f"[WX849] 唤醒登录过程中出错: {e}")
                                        logger.error("[WX849] 将尝试二维码登录")
                            except Exception as e:
                                logger.error(f"[WX849] 唤醒登录失败: {e}")
                    else:
                        logger.info("[WX849] 没有获取到缓存登录信息，将使用二维码登录")
                except Exception as e:
                    logger.error(f"[WX849] 获取缓存登录信息失败: {e}")
            else:
                logger.info("[WX849] 未找到保存的Wxid，跳过二次登录")
                
        except Exception as e:
            logger.error(f"[WX849] 自动登录过程出错: {e}")
            logger.info("[WX849] 将尝试二维码登录")

        # 如果二次登录和唤醒登录都失败或跳过，进行扫码登录
        # 生成device_name和device_id（如果不存在）
        if not device_name:
            device_name = "DoW微信机器人"  # 默认设备名称
            if hasattr(self.bot, "create_device_name"):
                device_name = self.bot.create_device_name()
                # 保存生成的device_name到配置
                config = conf()
                config.set("wx849_device_name", device_name)
                config.save_user_datas()
                save_config()
                
        if not saved_device_id and hasattr(self.bot, "create_device_id"):
            saved_device_id = self.bot.create_device_id()
            # 保存生成的device_id到配置
            config = conf()
            config.set("wx849_device_id", saved_device_id)
            config.save_user_datas()
            save_config()
            
        # 获取登录二维码
        logger.info(f"[WX849] 开始获取登录二维码: device_name={device_name}, device_id={saved_device_id}")
        uuid, url = await self.bot.get_qr_code(device_id=saved_device_id, device_name=device_name, print_qr=True)
        logger.info(f"[WX849] 获取到登录uuid: {uuid}")
        logger.info(f"[WX849] 获取到登录二维码: {url}")
        
        # 等待扫码并登录
        login_timeout = 120
        while login_timeout > 0:
            try:
                # 检查登录状态
                login_success, login_result = await self.bot.check_login_uuid(uuid, device_id=saved_device_id)
                
                if login_success:
                    logger.info("[WX849] 扫码登录成功，已获取登录信息")
                    
                    # 设置用户信息
                    if isinstance(login_result, dict) and login_result.get("acctSectResp"):
                        self.wxid = login_result.get("acctSectResp").get("userName", "")
                        self.name = login_result.get("acctSectResp").get("nickName", "")
                        self.user_id = self.wxid
                        
                        # 保存wxid和device_id到配置
                        config = conf()
                        config.set("wx849_wxid", self.wxid)
                        if saved_device_id:
                            config.set("wx849_device_id", saved_device_id)
                        config.set("wx849_device_name", device_name)
                        config.save_user_datas()
                        # 同时将配置保存到配置文件
                        save_config()
                        logger.info(f"[WX849] 已保存登录信息到配置: wxid={self.wxid}, device_id={saved_device_id}, device_name={device_name}")
                        
                        logger.info(f"[WX849] 登录信息: user_id: {self.user_id}, nickname: {self.name}")
                        self.is_logged_in = True
                        
                        return True
                        
            except Exception as e:
                logger.error(f"[WX849] 检查扫码登录状态出错: {e}")
            
            # 等待2秒后再次检查
            await asyncio.sleep(2)
            login_timeout -= 2
            logger.info(f"[WX849] 等待扫码登录完成，剩余 {login_timeout} 秒...")

    async def _message_listener(self):
        """消息监听器"""
        logger.info("[WX849] 开始监听消息...")
        error_count = 0
        
        while self.is_running:
            try:
                # 获取新消息
                try:
                    # 注释掉频繁打印的调试日志
                    # logger.debug("[WX849] 正在获取新消息...")
                    messages = await self.bot.get_new_message()
                    # 重置错误计数
                    error_count = 0
                except Exception as e:
                    error_count += 1
                    error_msg = str(e)
                    
                    # 检查是否是登录相关错误
                    if "请先登录" in error_msg or "您已退出微信" in error_msg or "登录已失效" in error_msg or "Please login first" in error_msg:
                        logger.error(f"[WX849] 获取消息出错，登录已失效: {e}")
                    else:
                        # 其他错误正常记录
                        logger.error(f"[WX849] 获取消息出错: {e}")
                    
                    await asyncio.sleep(5)  # 出错后等待一段时间再重试
                    continue
                
                # 如果获取到消息，则处理
                if messages:
                    for idx, msg in enumerate(messages):
                        try:
                            logger.debug(f"[WX849] 处理第 {idx+1}/{len(messages)} 条消息")
                            # 判断是否是群消息
                            is_group = False
                            # 检查多种可能的群聊标识字段
                            if "roomId" in msg and msg["roomId"]:
                                is_group = True
                            elif "toUserName" in msg and msg["toUserName"] and msg["toUserName"].endswith("@chatroom"):
                                is_group = True
                            elif "ToUserName" in msg and msg["ToUserName"] and msg["ToUserName"].endswith("@chatroom"):
                                is_group = True
                            
                            if is_group:
                                logger.debug(f"[WX849] 识别为群聊消息")
                            else:
                                logger.debug(f"[WX849] 识别为私聊消息")
                            
                            # 创建消息对象
                            cmsg = WX849Message(msg, is_group)
                            
                            # 处理消息
                            if is_group:
                                self.handle_group(cmsg)
                            else:
                                self.handle_single(cmsg)
                        except Exception as e:
                            logger.error(f"[WX849] 处理消息出错: {e}")
                            # 打印完整的异常堆栈
                            import traceback
                            logger.error(f"[WX849] 异常堆栈: {traceback.format_exc()}")
                
                # 休眠一段时间
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"[WX849] 消息监听器出错: {e}")
                # 打印完整的异常堆栈
                import traceback
                logger.error(f"[WX849] 异常堆栈: {traceback.format_exc()}")
                await asyncio.sleep(5)  # 出错后等待一段时间再重试

    def startup(self):
        """启动函数"""
        logger.info("[WX849] 正在启动...")
        
        # 创建事件循环
        loop = asyncio.new_event_loop()
        
        # 定义启动任务
        async def startup_task():
            # 初始化机器人（登录）
            login_success = await self._initialize_bot()
            if login_success:
                logger.info("[WX849] 登录成功，准备启动消息监听...")
                self.is_running = True
                # 启动消息监听
                await self._message_listener()
            else:
                logger.error("[WX849] 初始化失败")
        
        # 在新线程中运行事件循环
        def run_loop():
            asyncio.set_event_loop(loop)
            loop.run_until_complete(startup_task())
        
        thread = threading.Thread(target=run_loop)
        thread.daemon = True
        thread.start()

    @_check
    def handle_single(self, cmsg: ChatMessage):
        """处理私聊消息"""
        try:
            # 处理消息内容和类型
            self._process_message(cmsg)
            
            # 只记录关键消息信息，减少日志输出
            if conf().get("log_level", "INFO") != "ERROR":
                logger.debug(f"[WX849] 私聊消息 - 类型: {cmsg.ctype}, ID: {cmsg.msg_id}, 内容: {cmsg.content[:20]}...")
            
            # 根据消息类型处理
            if cmsg.ctype == ContextType.VOICE and conf().get("speech_recognition") != True:
                logger.debug("[WX849] 语音识别功能未启用，跳过处理")
                return
            
            # 检查前缀匹配
            if cmsg.ctype == ContextType.TEXT:
                single_chat_prefix = conf().get("single_chat_prefix", [""])
                # 日志记录前缀配置，方便调试
                logger.debug(f"[WX849] 单聊前缀配置: {single_chat_prefix}")
                match_prefix = None
                for prefix in single_chat_prefix:
                    if prefix and cmsg.content.startswith(prefix):
                        logger.debug(f"[WX849] 匹配到前缀: {prefix}")
                        match_prefix = prefix
                        # 去除前缀
                        cmsg.content = cmsg.content[len(prefix):].strip()
                        logger.debug(f"[WX849] 去除前缀后的内容: {cmsg.content}")
                        break
                
                # 记录是否匹配
                if not match_prefix and single_chat_prefix and "" not in single_chat_prefix:
                    logger.debug(f"[WX849] 未匹配到前缀，消息被过滤: {cmsg.content}")
                    # 如果没有匹配到前缀且配置中没有空前缀，则直接返回，不处理该消息
                    return
            
            # 生成上下文
            context = self._compose_context(cmsg.ctype, cmsg.content, isgroup=False, msg=cmsg)
            if context:
                self.produce(context)
            else:
                logger.debug(f"[WX849] 生成上下文失败，跳过处理")
        except Exception as e:
            logger.error(f"[WX849] 处理私聊消息异常: {e}")
            if conf().get("log_level", "INFO") == "DEBUG":
                import traceback
                logger.debug(f"[WX849] 异常堆栈: {traceback.format_exc()}")

    @_check
    def handle_group(self, cmsg: ChatMessage):
        """处理群聊消息"""
        try:
            # 添加日志，记录处理前的消息基本信息
            logger.debug(f"[WX849] 开始处理群聊消息 - ID:{cmsg.msg_id} 类型:{cmsg.msg_type} 从:{cmsg.from_user_id}")
            
            # 处理消息内容和类型
            self._process_message(cmsg)
            
            # 只记录关键消息信息，减少日志输出
            if conf().get("log_level", "INFO") != "ERROR":
                logger.debug(f"[WX849] 群聊消息 - 类型: {cmsg.ctype}, 群ID: {cmsg.other_user_id}")
            
            # 根据消息类型处理
            if cmsg.ctype == ContextType.VOICE and conf().get("group_speech_recognition") != True:
                logger.debug("[WX849] 群聊语音识别功能未启用，跳过处理")
                return
            
            # 检查白名单
            if cmsg.from_user_id and hasattr(cmsg, 'from_user_id'):
                group_white_list = conf().get("group_name_white_list", ["ALL_GROUP"])
                # 检查是否启用了白名单
                if "ALL_GROUP" not in group_white_list:
                    # 获取群名
                    group_name = None
                    try:
                        # 使用同步方式获取群名，避免事件循环嵌套
                        chatrooms_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp", 'wx849_rooms.json')
                        
                        if os.path.exists(chatrooms_file):
                            try:
                                with open(chatrooms_file, 'r', encoding='utf-8') as f:
                                    chatrooms_info = json.load(f)
                                
                                if cmsg.from_user_id in chatrooms_info:
                                    group_name = chatrooms_info[cmsg.from_user_id].get("nickName")
                                    if group_name:
                                        logger.debug(f"[WX849] 从缓存获取到群名: {group_name}")
                            except Exception as e:
                                logger.error(f"[WX849] 读取群聊缓存失败: {e}")
                        
                        # 如果没有从缓存获取到群名，使用群ID作为备用
                        if not group_name:
                            group_name = cmsg.from_user_id
                            logger.debug(f"[WX849] 没有找到群名，使用群ID: {group_name}")
                        
                        logger.debug(f"[WX849] 群聊白名单检查 - 群名: {group_name}")
                    except Exception as e:
                        logger.error(f"[WX849] 获取群名称失败: {e}")
                        group_name = cmsg.from_user_id
                    
                    # 检查群名是否在白名单中
                    if group_name and group_name not in group_white_list:
                        # 使用群ID再次检查
                        if cmsg.from_user_id not in group_white_list:
                            logger.info(f"[WX849] 群聊不在白名单中，跳过处理: {group_name}")
                            return
                    
                    logger.debug(f"[WX849] 群聊通过白名单检查: {group_name or cmsg.from_user_id}")
            
            # 检查前缀匹配
            trigger_proceed = False
            if cmsg.ctype == ContextType.TEXT:
                group_chat_prefix = conf().get("group_chat_prefix", [])
                group_chat_keyword = conf().get("group_chat_keyword", [])
                
                # 日志记录前缀配置，方便调试
                logger.debug(f"[WX849] 群聊前缀配置: {group_chat_prefix}")
                logger.debug(f"[WX849] 群聊关键词配置: {group_chat_keyword}")
                
                # 检查前缀匹配
                for prefix in group_chat_prefix:
                    if prefix and cmsg.content.startswith(prefix):
                        logger.debug(f"[WX849] 群聊匹配到前缀: {prefix}")
                        # 去除前缀
                        cmsg.content = cmsg.content[len(prefix):].strip()
                        logger.debug(f"[WX849] 去除前缀后的内容: {cmsg.content}")
                        trigger_proceed = True
                        break
                
                # 检查关键词匹配
                if not trigger_proceed and group_chat_keyword:
                    for keyword in group_chat_keyword:
                        if keyword and keyword in cmsg.content:
                            logger.debug(f"[WX849] 群聊匹配到关键词: {keyword}")
                            trigger_proceed = True
                            break
                
                # 检查是否@了机器人（增强版）
                if not trigger_proceed and (cmsg.at_list or cmsg.content.find("@") >= 0):
                    logger.debug(f"[WX849] @列表: {cmsg.at_list}, 机器人wxid: {self.wxid}")
                    
                    # 检查at_list中是否包含机器人wxid
                    at_matched = False
                    if cmsg.at_list and self.wxid in cmsg.at_list:
                        at_matched = True
                        logger.debug(f"[WX849] 在at_list中匹配到机器人wxid: {self.wxid}")
                    
                    # 如果at_list为空，或者at_list中没有找到机器人wxid，则检查消息内容中是否直接包含@机器人的文本
                    if not at_matched and cmsg.content:
                        # 获取可能的机器人名称
                        robot_names = []
                        if self.name:
                            robot_names.append(self.name)
                        if hasattr(cmsg, 'self_display_name') and cmsg.self_display_name:
                            robot_names.append(cmsg.self_display_name)
                            
                        # 检查消息中是否包含@机器人名称
                        for name in robot_names:
                            at_text = f"@{name}"
                            if at_text in cmsg.content:
                                at_matched = True
                                logger.debug(f"[WX849] 在消息内容中直接匹配到@机器人: {at_text}")
                                break
                    
                    # 处理多种可能的@格式
                    if at_matched:
                        # 尝试移除不同格式的@文本
                        original_content = cmsg.content
                        at_patterns = []
                        
                        # 添加可能的@格式
                        if self.name:
                            at_patterns.extend([
                                f"@{self.name} ",  # 带空格
                                f"@{self.name}\u2005",  # 带特殊空格
                                f"@{self.name}",  # 不带空格
                            ])
                        
                        # 检查是否存在自定义的群内昵称
                        if hasattr(cmsg, 'self_display_name') and cmsg.self_display_name:
                            at_patterns.extend([
                                f"@{cmsg.self_display_name} ",  # 带空格
                                f"@{cmsg.self_display_name}\u2005",  # 带特殊空格
                                f"@{cmsg.self_display_name}",  # 不带空格
                            ])
                        
                        # 按照优先级尝试移除@文本
                        for pattern in at_patterns:
                            if pattern in cmsg.content:
                                cmsg.content = cmsg.content.replace(pattern, "", 1).strip()
                                logger.debug(f"[WX849] 匹配到@模式: {pattern}")
                                logger.debug(f"[WX849] 去除@后的内容: {cmsg.content}")
                                break
                        
                        # 如果没有匹配到任何@模式，但确实在at_list中找到了机器人或内容中包含@
                        # 尝试使用正则表达式移除通用@格式
                        if cmsg.content == original_content and at_matched:
                            import re
                            # 匹配形如"@任何内容 "的模式
                            at_pattern = re.compile(r'@[^\s]+[\s\u2005]+')
                            cmsg.content = at_pattern.sub("", cmsg.content, 1).strip()
                            logger.debug(f"[WX849] 使用正则表达式去除@后的内容: {cmsg.content}")
                        
                        trigger_proceed = True
                
                # 记录是否需要处理
                if not trigger_proceed:
                    logger.debug(f"[WX849] 群聊消息未匹配触发条件，跳过处理: {cmsg.content}")
                    return
            
            # 生成上下文
            context = self._compose_context(cmsg.ctype, cmsg.content, isgroup=True, msg=cmsg)
            if context:
                self.produce(context)
            else:
                logger.debug(f"[WX849] 生成群聊上下文失败，跳过处理")
        except Exception as e:
            error_msg = str(e)
            # 添加更详细的错误日志信息
            logger.error(f"[WX849] 处理群聊消息异常: {error_msg}")
            logger.error(f"[WX849] 消息内容: {getattr(cmsg, 'content', '未知')[:100]}")
            logger.error(f"[WX849] 消息类型: {getattr(cmsg, 'msg_type', '未知')}")
            logger.error(f"[WX849] 上下文类型: {getattr(cmsg, 'ctype', '未知')}")
            
            # 记录完整的异常堆栈
            import traceback
            logger.error(f"[WX849] 异常堆栈: {traceback.format_exc()}")

    def _process_message(self, cmsg):
        """处理消息内容和类型"""
        # 处理消息类型
        msg_type = cmsg.msg_type
        if not msg_type and "Type" in cmsg.msg:
            msg_type = cmsg.msg["Type"]
        
        # 尝试获取机器人在群内的昵称
        if cmsg.is_group and not cmsg.self_display_name:
            try:
                # 从缓存中查询群成员详情
                tmp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp")
                chatrooms_file = os.path.join(tmp_dir, 'wx849_rooms.json')
                
                if os.path.exists(chatrooms_file):
                    try:
                        with open(chatrooms_file, 'r', encoding='utf-8') as f:
                            chatrooms_info = json.load(f)
                        
                        if cmsg.from_user_id in chatrooms_info:
                            room_info = chatrooms_info[cmsg.from_user_id]
                            
                            # 在成员中查找机器人的信息
                            if "members" in room_info and isinstance(room_info["members"], list):
                                for member in room_info["members"]:
                                    if member.get("UserName") == self.wxid:
                                        # 优先使用群内显示名称
                                        if member.get("DisplayName"):
                                            cmsg.self_display_name = member.get("DisplayName")
                                            logger.debug(f"[WX849] 从群成员缓存中获取到机器人群内昵称: {cmsg.self_display_name}")
                                            break
                                        # 其次使用昵称
                                        elif member.get("NickName"):
                                            cmsg.self_display_name = member.get("NickName")
                                            logger.debug(f"[WX849] 从群成员缓存中获取到机器人昵称: {cmsg.self_display_name}")
                                            break
                    except Exception as e:
                        logger.error(f"[WX849] 读取群成员缓存失败: {e}")
                
                # 如果缓存中没有找到，使用机器人名称
                if not cmsg.self_display_name:
                    cmsg.self_display_name = self.name
                    logger.debug(f"[WX849] 使用机器人名称作为群内昵称: {cmsg.self_display_name}")
            except Exception as e:
                logger.error(f"[WX849] 获取机器人群内昵称失败: {e}")
        
        # 根据消息类型进行处理
        if msg_type in [1, "1", "Text"]:
            self._process_text_message(cmsg)
        elif msg_type in [3, "3", "Image"]:
            self._process_image_message(cmsg)
        elif msg_type in [34, "34", "Voice"]:
            self._process_voice_message(cmsg)
        elif msg_type in [43, "43", "Video"]:
            self._process_video_message(cmsg)
        elif msg_type in [47, "47", "Emoji"]:
            self._process_emoji_message(cmsg)
        elif msg_type in [49, "49", "App"]:
            self._process_xml_message(cmsg)
        elif msg_type in [10000, "10000", "System"]:
            self._process_system_message(cmsg)
        else:
            # 默认类型处理
            cmsg.ctype = ContextType.UNKNOWN
            logger.warning(f"[WX849] 未知消息类型: {msg_type}, 内容: {cmsg.content[:100]}")
        
        # 检查消息是否来自群聊
        if cmsg.is_group or cmsg.from_user_id.endswith("@chatroom"):
            # 增强的群消息发送者提取逻辑
            # 尝试多种可能的格式解析发送者信息
            sender_extracted = False
            
            # 方法1: 尝试解析完整的格式 "wxid:\n消息内容"
            split_content = cmsg.content.split(":\n", 1)
            if len(split_content) > 1 and split_content[0] and not split_content[0].startswith("<"):
                cmsg.sender_wxid = split_content[0]
                cmsg.content = split_content[1]
                sender_extracted = True
                logger.debug(f"[WX849] 群聊发送者提取(方法1): {cmsg.sender_wxid}")
            
            # 方法2: 尝试解析简单的格式 "wxid:消息内容"
            if not sender_extracted:
                split_content = cmsg.content.split(":", 1)
                if len(split_content) > 1 and split_content[0] and not split_content[0].startswith("<"):
                    cmsg.sender_wxid = split_content[0]
                    cmsg.content = split_content[1]
                    sender_extracted = True
                    logger.debug(f"[WX849] 群聊发送者提取(方法2): {cmsg.sender_wxid}")
            
            # 方法3: 尝试从回复XML中提取
            if not sender_extracted and cmsg.content and cmsg.content.startswith("<"):
                try:
                    # 解析XML内容
                    root = ET.fromstring(cmsg.content)
                    
                    # 查找不同类型的XML中可能存在的发送者信息
                    if root.tag == "msg":
                        # 常见的XML消息格式
                        sender_node = root.find(".//username")
                        if sender_node is not None and sender_node.text:
                            cmsg.sender_wxid = sender_node.text
                            sender_extracted = True
                            logger.debug(f"[WX849] 群聊发送者从XML提取: {cmsg.sender_wxid}")
                        
                        # 尝试其他可能的标签
                        if not sender_extracted:
                            for tag in ["fromusername", "sender", "from"]:
                                sender_node = root.find(f".//{tag}")
                                if sender_node is not None and sender_node.text:
                                    cmsg.sender_wxid = sender_node.text
                                    sender_extracted = True
                                    logger.debug(f"[WX849] 群聊发送者从XML({tag})提取: {cmsg.sender_wxid}")
                                    break
                except Exception as e:
                    logger.error(f"[WX849] 从XML提取群聊发送者失败: {e}")
            
            # 方法4: 尝试从其它字段提取
            if not sender_extracted:
                for key in ["SenderUserName", "sender", "senderId", "fromUser"]:
                    if key in cmsg.msg and cmsg.msg[key]:
                        cmsg.sender_wxid = str(cmsg.msg[key])
                        sender_extracted = True
                        logger.debug(f"[WX849] 群聊发送者从字段提取({key}): {cmsg.sender_wxid}")
                        break
            
            # 如果仍然无法提取，设置为默认值但不要留空
            if not sender_extracted or not cmsg.sender_wxid:
                cmsg.sender_wxid = f"未知用户_{cmsg.from_user_id}"
                logger.debug(f"[WX849] 无法提取群聊发送者，使用默认值: {cmsg.sender_wxid}")
            
            # 设置other_user_id为群ID，确保它不为None
            cmsg.other_user_id = cmsg.from_user_id
            
            # 设置actual_user_id为发送者wxid
            cmsg.actual_user_id = cmsg.sender_wxid
            
            # 异步获取发送者昵称并设置actual_user_nickname
            # 但现在我们无法在同步方法中直接调用异步方法，所以先使用wxid
            cmsg.actual_user_nickname = cmsg.sender_wxid
            
            # 启动异步任务获取昵称并更新actual_user_nickname
            threading.Thread(target=lambda: asyncio.run(self._update_nickname_async(cmsg))).start()
            
            logger.debug(f"[WX849] 设置实际发送者信息: actual_user_id={cmsg.actual_user_id}, actual_user_nickname={cmsg.actual_user_nickname}")
        else:
            # 私聊消息
            cmsg.sender_wxid = cmsg.from_user_id
            cmsg.is_group = False
            
            # 私聊消息也设置actual_user_id和actual_user_nickname
            cmsg.actual_user_id = cmsg.from_user_id
            cmsg.actual_user_nickname = cmsg.from_user_id
            logger.debug(f"[WX849] 设置私聊发送者信息: actual_user_id={cmsg.actual_user_id}, actual_user_nickname={cmsg.actual_user_nickname}")

    async def _update_nickname_async(self, cmsg):
        """异步更新消息中的昵称信息"""
        if cmsg.is_group and cmsg.from_user_id.endswith("@chatroom"):
            nickname = await self._get_chatroom_member_nickname(cmsg.from_user_id, cmsg.sender_wxid)
            if nickname and nickname != cmsg.actual_user_nickname:
                cmsg.actual_user_nickname = nickname
                logger.debug(f"[WX849] 异步更新了发送者昵称: {nickname}")

    def _process_text_message(self, cmsg):
        """处理文本消息"""
        import xml.etree.ElementTree as ET
        
        cmsg.ctype = ContextType.TEXT
        
        # 处理群聊/私聊消息发送者
        if cmsg.is_group or cmsg.from_user_id.endswith("@chatroom"):
            cmsg.is_group = True
            
            # 增强的群消息发送者提取逻辑
            # 尝试多种可能的格式解析发送者信息
            sender_extracted = False
            
            # 方法1: 尝试解析完整的格式 "wxid:\n消息内容"
            split_content = cmsg.content.split(":\n", 1)
            if len(split_content) > 1 and split_content[0] and not split_content[0].startswith("<"):
                cmsg.sender_wxid = split_content[0]
                cmsg.content = split_content[1]
                sender_extracted = True
                logger.debug(f"[WX849] 群聊发送者提取(方法1): {cmsg.sender_wxid}")
            
            # 方法2: 尝试解析简单的格式 "wxid:消息内容"
            if not sender_extracted:
                split_content = cmsg.content.split(":", 1)
                if len(split_content) > 1 and split_content[0] and not split_content[0].startswith("<"):
                    cmsg.sender_wxid = split_content[0]
                    cmsg.content = split_content[1]
                    sender_extracted = True
                    logger.debug(f"[WX849] 群聊发送者提取(方法2): {cmsg.sender_wxid}")
            
            # 方法3: 尝试从MsgSource XML中提取
            if not sender_extracted:
                try:
                    msg_source = cmsg.msg.get("MsgSource", "")
                    if msg_source and (msg_source.startswith("<") or "<msgsource>" in msg_source.lower()):
                        try:
                            if "<msgsource>" not in msg_source.lower():
                                msg_source = f"<msgsource>{msg_source}</msgsource>"
                            root = ET.fromstring(msg_source)
                            # 尝试提取不同可能的发送者标签
                            for tag in ["username", "nickname", "alias", "fromusername"]:
                                elem = root.find(f"./{tag}")
                                if elem is not None and elem.text:
                                    cmsg.sender_wxid = elem.text
                                    sender_extracted = True
                                    logger.debug(f"[WX849] 群聊发送者从MsgSource提取(标签:{tag}): {cmsg.sender_wxid}")
                                    break
                                    
                            # 同时尝试提取机器人在群内的昵称
                            for tag in ["selfDisplayName", "displayname", "nickname"]:
                                elem = root.find(f"./{tag}")
                                if elem is not None and elem.text:
                                    cmsg.self_display_name = elem.text
                                    logger.debug(f"[WX849] 从MsgSource中提取到机器人群内昵称: {cmsg.self_display_name}")
                                    break
                        except Exception as e:
                            logger.debug(f"[WX849] 从MsgSource提取发送者失败: {e}")
                except Exception as e:
                    logger.debug(f"[WX849] 尝试解析MsgSource时出错: {e}")
            
            # 方法4: 尝试从其它字段提取
            if not sender_extracted:
                for key in ["SenderUserName", "sender", "senderId", "fromUser"]:
                    if key in cmsg.msg and cmsg.msg[key]:
                        cmsg.sender_wxid = str(cmsg.msg[key])
                        sender_extracted = True
                        logger.debug(f"[WX849] 群聊发送者从字段提取({key}): {cmsg.sender_wxid}")
                        break
            
            # 如果仍然无法提取，设置为默认值但不要留空
            if not sender_extracted or not cmsg.sender_wxid:
                cmsg.sender_wxid = f"未知用户_{cmsg.from_user_id}"
                logger.debug(f"[WX849] 无法提取群聊发送者，使用默认值: {cmsg.sender_wxid}")
            
            # 设置other_user_id为群ID，确保它不为None
            cmsg.other_user_id = cmsg.from_user_id
            
            # 设置actual_user_id和actual_user_nickname
            cmsg.actual_user_id = cmsg.sender_wxid
            cmsg.actual_user_nickname = cmsg.sender_wxid
            logger.debug(f"[WX849] 设置实际发送者信息: actual_user_id={cmsg.actual_user_id}, actual_user_nickname={cmsg.actual_user_nickname}")
        else:
            # 私聊消息
            cmsg.sender_wxid = cmsg.from_user_id
            cmsg.is_group = False
        
            # 私聊消息也设置actual_user_id和actual_user_nickname
            cmsg.actual_user_id = cmsg.from_user_id
            cmsg.actual_user_nickname = cmsg.from_user_id
            logger.debug(f"[WX849] 设置私聊发送者信息: actual_user_id={cmsg.actual_user_id}, actual_user_nickname={cmsg.actual_user_nickname}")
        
        # 解析@信息 - 多种方式解析
        try:
            # 方法1: 从MsgSource解析
            msg_source = cmsg.msg.get("MsgSource", "")
            if msg_source:
                try:
                    if "<msgsource>" not in msg_source.lower():
                        msg_source = f"<msgsource>{msg_source}</msgsource>"
                    root = ET.fromstring(msg_source)
                    ats_elem = root.find(".//atuserlist")
                    if ats_elem is not None and ats_elem.text:
                        cmsg.at_list = [x for x in ats_elem.text.strip(",").split(",") if x]
                        logger.debug(f"[WX849] 从MsgSource解析到@列表: {cmsg.at_list}")
                except Exception as e:
                    logger.debug(f"[WX849] 从MsgSource解析@列表失败: {e}")
            
            # 方法2: 从其他字段解析
            if not cmsg.at_list:
                for key in ["AtUserList", "at_list", "atlist"]:
                    if key in cmsg.msg:
                        at_value = cmsg.msg[key]
                        if isinstance(at_value, list):
                            cmsg.at_list = [str(x) for x in at_value if x]
                        elif isinstance(at_value, str):
                            cmsg.at_list = [x for x in at_value.strip(",").split(",") if x]
                        
                        if cmsg.at_list:
                            logger.debug(f"[WX849] 从字段{key}解析到@列表: {cmsg.at_list}")
                            break
            
            # 方法3: 从消息内容中检测@机器人
            if cmsg.is_group and not cmsg.at_list and "@" in cmsg.content:
                # 如果机器人有名称或群内昵称，检查是否被@
                if self.name and f"@{self.name}" in cmsg.content:
                    # 模拟添加自己到at_list
                    cmsg.at_list.append(self.wxid)
                    logger.debug(f"[WX849] 从消息内容检测到@机器人名称: {self.name}")
                elif hasattr(cmsg, 'self_display_name') and cmsg.self_display_name and f"@{cmsg.self_display_name}" in cmsg.content:
                    # 模拟添加自己到at_list
                    cmsg.at_list.append(self.wxid)
                    logger.debug(f"[WX849] 从消息内容检测到@机器人群内昵称: {cmsg.self_display_name}")
        except Exception as e:
            logger.debug(f"[WX849] 解析@列表失败: {e}")
            cmsg.at_list = []
        
        # 确保at_list不为空列表
        if not cmsg.at_list or (len(cmsg.at_list) == 1 and cmsg.at_list[0] == ""):
            cmsg.at_list = []
        
        # 输出日志
        logger.info(f"收到文本消息: ID:{cmsg.msg_id} 来自:{cmsg.from_user_id} 发送人:{cmsg.sender_wxid} @:{cmsg.at_list} 内容:{cmsg.content}")

    def _process_image_message(self, cmsg):
        """处理图片消息"""
        import xml.etree.ElementTree as ET
        
        cmsg.ctype = ContextType.IMAGE
        
        # 处理群聊/私聊消息发送者
        if cmsg.is_group or cmsg.from_user_id.endswith("@chatroom"):
            cmsg.is_group = True
            split_content = cmsg.content.split(":\n", 1)
            if len(split_content) > 1:
                cmsg.sender_wxid = split_content[0]
                cmsg.content = split_content[1]
            else:
                # 处理没有换行的情况
                split_content = cmsg.content.split(":", 1)
                if len(split_content) > 1:
                    cmsg.sender_wxid = split_content[0]
                    cmsg.content = split_content[1]
                else:
                    cmsg.content = split_content[0]
                    cmsg.sender_wxid = ""
            
            # 设置actual_user_id和actual_user_nickname
            cmsg.actual_user_id = cmsg.sender_wxid
            cmsg.actual_user_nickname = cmsg.sender_wxid
        else:
            # 私聊消息
            cmsg.sender_wxid = cmsg.from_user_id
            cmsg.is_group = False
            
            # 私聊消息也设置actual_user_id和actual_user_nickname
            cmsg.actual_user_id = cmsg.from_user_id
            cmsg.actual_user_nickname = cmsg.from_user_id
        
        # 解析图片信息
        try:
            root = ET.fromstring(cmsg.content)
            img_element = root.find('img')
            if img_element is not None:
                cmsg.image_info = {
                    'aeskey': img_element.get('aeskey'),
                    'cdnmidimgurl': img_element.get('cdnmidimgurl'),
                    'length': img_element.get('length'),
                    'md5': img_element.get('md5')
                }
                logger.debug(f"解析图片XML成功: aeskey={cmsg.image_info['aeskey']}, length={cmsg.image_info['length']}, md5={cmsg.image_info['md5']}")
        except Exception as e:
            logger.debug(f"解析图片消息失败: {e}, 内容: {cmsg.content[:100]}")
            cmsg.image_info = {}
        
        # 输出日志 - 修改为显示完整XML内容
        logger.info(f"收到图片消息: ID:{cmsg.msg_id} 来自:{cmsg.from_user_id} 发送人:{cmsg.sender_wxid}\nXML内容: {cmsg.content}")

    def _process_voice_message(self, cmsg):
        """处理语音消息"""
        import xml.etree.ElementTree as ET
        import re
        
        cmsg.ctype = ContextType.VOICE
        
        # 保存原始内容，避免修改
        original_content = cmsg.content
        
        # 检查内容是否为XML格式
        is_xml_content = original_content.strip().startswith("<?xml") or original_content.strip().startswith("<msg")
        
        # 首先尝试从XML中提取发送者信息
        if is_xml_content:
            logger.debug(f"[WX849] 语音消息：尝试从XML提取发送者")
            try:
                # 使用正则表达式从XML字符串中提取fromusername属性或元素
                match = re.search(r'fromusername\s*=\s*["\'](.*?)["\']', original_content)
                if match:
                    cmsg.sender_wxid = match.group(1)
                    logger.debug(f"[WX849] 语音消息：从XML属性提取的发送者ID: {cmsg.sender_wxid}")
                else:
                    # 尝试从元素中提取
                    match = re.search(r'<fromusername>(.*?)</fromusername>', original_content)
                    if match:
                        cmsg.sender_wxid = match.group(1)
                        logger.debug(f"[WX849] 语音消息：从XML元素提取的发送者ID: {cmsg.sender_wxid}")
                    else:
                        logger.debug("[WX849] 语音消息：未找到fromusername")
                        
                        # 尝试使用ElementTree解析
                        try:
                            root = ET.fromstring(original_content)
                            # 尝试查找语音元素的fromusername属性
                            voice_element = root.find('voicemsg')
                            if voice_element is not None and 'fromusername' in voice_element.attrib:
                                cmsg.sender_wxid = voice_element.attrib['fromusername']
                                logger.debug(f"[WX849] 语音消息：使用ElementTree提取的发送者ID: {cmsg.sender_wxid}")
                        except Exception as e:
                            logger.debug(f"[WX849] 语音消息：使用ElementTree解析失败: {e}")
            except Exception as e:
                logger.debug(f"[WX849] 语音消息：提取发送者失败: {e}")
                
        # 如果无法从XML提取，再尝试传统的分割方法
        if not cmsg.sender_wxid and (cmsg.is_group or cmsg.from_user_id.endswith("@chatroom")):
            cmsg.is_group = True
            split_content = original_content.split(":\n", 1)
            if len(split_content) > 1:
                cmsg.sender_wxid = split_content[0]
                logger.debug(f"[WX849] 语音消息：使用分割方法提取的发送者ID: {cmsg.sender_wxid}")
            else:
                # 处理没有换行的情况
                split_content = original_content.split(":", 1)
                if len(split_content) > 1:
                    cmsg.sender_wxid = split_content[0]
                    logger.debug(f"[WX849] 语音消息：使用冒号分割提取的发送者ID: {cmsg.sender_wxid}")
        
        # 对于私聊消息，使用from_user_id作为发送者ID
        if not cmsg.sender_wxid and not cmsg.is_group:
            cmsg.sender_wxid = cmsg.from_user_id
            cmsg.is_group = False
        
        # 设置actual_user_id和actual_user_nickname
        cmsg.actual_user_id = cmsg.sender_wxid or cmsg.from_user_id
        cmsg.actual_user_nickname = cmsg.sender_wxid or cmsg.from_user_id
        
        # 解析语音信息 (保留此功能以获取语音URL等信息)
        try:
            root = ET.fromstring(original_content)
            voice_element = root.find('voicemsg')
            if voice_element is not None:
                cmsg.voice_info = {
                    'voiceurl': voice_element.get('voiceurl'),
                    'length': voice_element.get('length')
                }
                logger.debug(f"解析语音XML成功: voiceurl={cmsg.voice_info['voiceurl']}, length={cmsg.voice_info['length']}")
        except Exception as e:
            logger.debug(f"解析语音消息失败: {e}, 内容: {original_content[:100]}")
            cmsg.voice_info = {}
            
        # 确保保留原始XML内容
        cmsg.content = original_content
        
        # 最终检查，确保发送者不是XML内容
        if not cmsg.sender_wxid or "<" in cmsg.sender_wxid:
            cmsg.sender_wxid = "未知发送者"
            cmsg.actual_user_id = cmsg.sender_wxid
            cmsg.actual_user_nickname = cmsg.sender_wxid
        
        # 输出日志，显示完整XML内容
        logger.info(f"收到语音消息: ID:{cmsg.msg_id} 来自:{cmsg.from_user_id} 发送人:{cmsg.sender_wxid}\nXML内容: {cmsg.content}")

    def _process_video_message(self, cmsg):
        """处理视频消息"""
        import xml.etree.ElementTree as ET
        import re
        
        cmsg.ctype = ContextType.VIDEO
        
        # 保存原始内容，避免修改
        original_content = cmsg.content
        
        # 检查内容是否为XML格式
        is_xml_content = original_content.strip().startswith("<?xml") or original_content.strip().startswith("<msg")
        
        # 首先尝试从XML中提取发送者信息
        if is_xml_content:
            logger.debug(f"[WX849] 视频消息：尝试从XML提取发送者")
            try:
                # 使用正则表达式从XML字符串中提取fromusername属性或元素
                match = re.search(r'fromusername\s*=\s*["\'](.*?)["\']', original_content)
                if match:
                    cmsg.sender_wxid = match.group(1)
                    logger.debug(f"[WX849] 视频消息：从XML属性提取的发送者ID: {cmsg.sender_wxid}")
                else:
                    # 尝试从元素中提取
                    match = re.search(r'<fromusername>(.*?)</fromusername>', original_content)
                    if match:
                        cmsg.sender_wxid = match.group(1)
                        logger.debug(f"[WX849] 视频消息：从XML元素提取的发送者ID: {cmsg.sender_wxid}")
                    else:
                        logger.debug("[WX849] 视频消息：未找到fromusername")
                        
                        # 尝试使用ElementTree解析
                        try:
                            root = ET.fromstring(original_content)
                            # 尝试查找video元素的fromusername属性
                            video_element = root.find('videomsg')
                            if video_element is not None and 'fromusername' in video_element.attrib:
                                cmsg.sender_wxid = video_element.attrib['fromusername']
                                logger.debug(f"[WX849] 视频消息：使用ElementTree提取的发送者ID: {cmsg.sender_wxid}")
                        except Exception as e:
                            logger.debug(f"[WX849] 视频消息：使用ElementTree解析失败: {e}")
            except Exception as e:
                logger.debug(f"[WX849] 视频消息：提取发送者失败: {e}")
                
        # 如果无法从XML提取，再尝试传统的分割方法
        if not cmsg.sender_wxid and (cmsg.is_group or cmsg.from_user_id.endswith("@chatroom")):
            cmsg.is_group = True
            split_content = original_content.split(":\n", 1)
            if len(split_content) > 1:
                cmsg.sender_wxid = split_content[0]
                logger.debug(f"[WX849] 视频消息：使用分割方法提取的发送者ID: {cmsg.sender_wxid}")
            else:
                # 处理没有换行的情况
                split_content = original_content.split(":", 1)
                if len(split_content) > 1:
                    cmsg.sender_wxid = split_content[0]
                    logger.debug(f"[WX849] 视频消息：使用冒号分割提取的发送者ID: {cmsg.sender_wxid}")
        
        # 对于私聊消息，使用from_user_id作为发送者ID
        if not cmsg.sender_wxid and not cmsg.is_group:
            cmsg.sender_wxid = cmsg.from_user_id
            cmsg.is_group = False
            
        # 设置actual_user_id和actual_user_nickname
        cmsg.actual_user_id = cmsg.sender_wxid or cmsg.from_user_id
        cmsg.actual_user_nickname = cmsg.sender_wxid or cmsg.from_user_id
            
        # 确保保留原始XML内容
        cmsg.content = original_content
        
        # 最终检查，确保发送者不是XML内容
        if not cmsg.sender_wxid or "<" in cmsg.sender_wxid:
            cmsg.sender_wxid = "未知发送者"
            cmsg.actual_user_id = cmsg.sender_wxid
            cmsg.actual_user_nickname = cmsg.sender_wxid
        
        # 输出日志，显示完整XML内容
        logger.info(f"收到视频消息: ID:{cmsg.msg_id} 来自:{cmsg.from_user_id} 发送人:{cmsg.sender_wxid}\nXML内容: {cmsg.content}")

    def _process_emoji_message(self, cmsg):
        """处理表情消息"""
        import xml.etree.ElementTree as ET
        import re
        
        cmsg.ctype = ContextType.TEXT  # 表情消息通常也用TEXT类型
        
        # 保存原始内容，避免修改
        original_content = cmsg.content
        
        # 检查内容是否为XML格式
        is_xml_content = original_content.strip().startswith("<?xml") or original_content.strip().startswith("<msg")
        
        # 首先尝试从XML中提取发送者信息
        if is_xml_content:
            logger.debug(f"[WX849] 表情消息：尝试从XML提取发送者")
            try:
                # 使用正则表达式从XML中提取fromusername属性
                match = re.search(r'fromusername\s*=\s*["\'](.*?)["\']', original_content)
                if match:
                    cmsg.sender_wxid = match.group(1)
                    logger.debug(f"[WX849] 表情消息：从XML提取的发送者ID: {cmsg.sender_wxid}")
                else:
                    logger.debug("[WX849] 表情消息：未找到fromusername属性")
                    
                    # 尝试使用ElementTree解析
                    try:
                        root = ET.fromstring(original_content)
                        emoji_element = root.find('emoji')
                        if emoji_element is not None and 'fromusername' in emoji_element.attrib:
                            cmsg.sender_wxid = emoji_element.attrib['fromusername']
                            logger.debug(f"[WX849] 表情消息：使用ElementTree提取的发送者ID: {cmsg.sender_wxid}")
                    except Exception as e:
                        logger.debug(f"[WX849] 表情消息：使用ElementTree解析失败: {e}")
            except Exception as e:
                logger.debug(f"[WX849] 表情消息：提取发送者失败: {e}")
                
        # 如果无法从XML提取，再尝试传统的分割方法
        if not cmsg.sender_wxid and (cmsg.is_group or cmsg.from_user_id.endswith("@chatroom")):
            cmsg.is_group = True
            split_content = original_content.split(":\n", 1)
            if len(split_content) > 1:
                cmsg.sender_wxid = split_content[0]
                logger.debug(f"[WX849] 表情消息：使用分割方法提取的发送者ID: {cmsg.sender_wxid}")
            else:
                # 处理没有换行的情况
                split_content = original_content.split(":", 1)
                if len(split_content) > 1:
                    cmsg.sender_wxid = split_content[0]
                    logger.debug(f"[WX849] 表情消息：使用冒号分割提取的发送者ID: {cmsg.sender_wxid}")
        
        # 对于私聊消息，使用from_user_id作为发送者ID
        if not cmsg.sender_wxid and not cmsg.is_group:
            cmsg.sender_wxid = cmsg.from_user_id
            cmsg.is_group = False
            
        # 设置actual_user_id和actual_user_nickname
        cmsg.actual_user_id = cmsg.sender_wxid or cmsg.from_user_id
        cmsg.actual_user_nickname = cmsg.sender_wxid or cmsg.from_user_id
            
        # 确保保留原始XML内容
        cmsg.content = original_content
        
        # 最终检查，确保发送者不是XML内容
        if not cmsg.sender_wxid or "<" in cmsg.sender_wxid:
            cmsg.sender_wxid = "未知发送者"
            cmsg.actual_user_id = cmsg.sender_wxid
            cmsg.actual_user_nickname = cmsg.sender_wxid
        
        # 输出日志，显示完整XML内容
        logger.info(f"收到表情消息: ID:{cmsg.msg_id} 来自:{cmsg.from_user_id} 发送人:{cmsg.sender_wxid} \nXML内容: {cmsg.content}")

    def _process_xml_message(self, cmsg):
        """处理XML消息"""
        # 只保留re模块的导入
        import re
        
        # 先默认设置为XML类型，添加错误处理
        try:
            cmsg.ctype = ContextType.XML
        except AttributeError:
            # 如果XML类型不存在，尝试添加它
            logger.error("[WX849] ContextType.XML 不存在，尝试动态添加")
            if not hasattr(ContextType, 'XML'):
                setattr(ContextType, 'XML', 'XML')
                logger.info("[WX849] 运行时添加 ContextType.XML 类型成功")
            try:
                cmsg.ctype = ContextType.XML
            except:
                # 如果仍然失败，回退到TEXT类型
                logger.error("[WX849] 设置 ContextType.XML 失败，回退到 TEXT 类型")
                cmsg.ctype = ContextType.TEXT
        
        # 添加调试日志，记录原始XML内容
        logger.debug(f"[WX849] 开始处理XML消息，消息ID: {cmsg.msg_id}, 内容长度: {len(cmsg.content)}")
        if cmsg.content and len(cmsg.content) > 0:
            logger.debug(f"[WX849] XML内容前100字符: {cmsg.content[:100]}")
        else:
            logger.debug(f"[WX849] XML内容为空")
        
        # 检查内容是否为XML格式
        original_content = cmsg.content
        is_xml_content = original_content.strip().startswith("<?xml") or original_content.strip().startswith("<msg")
        
        # 处理群聊/私聊消息发送者
        if cmsg.is_group or cmsg.from_user_id.endswith("@chatroom"):
            cmsg.is_group = True
            # 先默认设置一个空的sender_wxid
            cmsg.sender_wxid = ""
            
            # 尝试从XML中提取发送者信息
            if is_xml_content:
                logger.debug(f"[WX849] XML消息：尝试从XML提取发送者")
                try:
                    # 使用正则表达式从XML中提取fromusername属性
                    match = re.search(r'fromusername\s*=\s*["\'](.*?)["\']', original_content)
                    if match:
                        cmsg.sender_wxid = match.group(1)
                        logger.debug(f"[WX849] XML消息：从XML提取的发送者ID: {cmsg.sender_wxid}")
                    else:
                        # 尝试从元素中提取
                        match = re.search(r'<fromusername>(.*?)</fromusername>', original_content)
                        if match:
                            cmsg.sender_wxid = match.group(1)
                            logger.debug(f"[WX849] XML消息：从XML元素提取的发送者ID: {cmsg.sender_wxid}")
                        else:
                            logger.debug("[WX849] XML消息：未找到fromusername")
                except Exception as e:
                    logger.debug(f"[WX849] XML消息：提取发送者失败: {e}")
            
            # 如果无法从XML提取，尝试传统的分割方法
            if not cmsg.sender_wxid:
                split_content = original_content.split(":\n", 1)
                if len(split_content) > 1 and not split_content[0].startswith("<"):
                    cmsg.sender_wxid = split_content[0]
                    logger.debug(f"[WX849] XML消息：使用分割方法提取的发送者ID: {cmsg.sender_wxid}")
                else:
                    # 处理没有换行的情况
                    split_content = original_content.split(":", 1)
                    if len(split_content) > 1 and not split_content[0].startswith("<"):
                        cmsg.sender_wxid = split_content[0]
                        logger.debug(f"[WX849] XML消息：使用冒号分割提取的发送者ID: {cmsg.sender_wxid}")
            
            # 如果仍然无法提取，使用默认值
            if not cmsg.sender_wxid:
                cmsg.sender_wxid = f"未知用户_{cmsg.from_user_id}"
                logger.debug(f"[WX849] XML消息：使用默认发送者ID: {cmsg.sender_wxid}")
        else:
            # 私聊消息
            cmsg.sender_wxid = cmsg.from_user_id
            cmsg.is_group = False
        
        # 设置actual_user_id和actual_user_nickname
        cmsg.actual_user_id = cmsg.sender_wxid or cmsg.from_user_id
        cmsg.actual_user_nickname = cmsg.sender_wxid or cmsg.from_user_id
        
        # 输出日志，显示完整XML内容
        logger.info(f"收到XML消息: ID:{cmsg.msg_id} 来自:{cmsg.from_user_id} 发送人:{cmsg.sender_wxid}\nXML内容: {cmsg.content}")

    def _process_system_message(self, cmsg):
        """处理系统消息"""
        # 移除重复导入的ET
        
        # 检查是否是拍一拍消息
        if "<pat" in cmsg.content:
            try:
                root = ET.fromstring(cmsg.content)
                pat = root.find("pat")
                if pat is not None:
                    cmsg.ctype = ContextType.PAT  # 使用自定义类型
                    patter = pat.find("fromusername").text if pat.find("fromusername") is not None else ""
                    patted = pat.find("pattedusername").text if pat.find("pattedusername") is not None else ""
                    pat_suffix = pat.find("patsuffix").text if pat.find("patsuffix") is not None else ""
                    cmsg.pat_info = {
                        "patter": patter,
                        "patted": patted,
                        "suffix": pat_suffix
                    }
                    
                    # 设置actual_user_id和actual_user_nickname
                    cmsg.sender_wxid = patter
                    cmsg.actual_user_id = patter
                    cmsg.actual_user_nickname = patter
                    
                    # 日志输出
                    logger.info(f"收到拍一拍消息: ID:{cmsg.msg_id} 来自:{cmsg.from_user_id} 发送人:{cmsg.sender_wxid} 拍者:{patter} 被拍:{patted} 后缀:{pat_suffix}")
                    return
            except Exception as e:
                logger.debug(f"[WX849] 解析拍一拍消息失败: {e}")
        
        # 如果不是特殊系统消息，按普通系统消息处理
        cmsg.ctype = ContextType.SYSTEM
        
        # 设置系统消息的actual_user_id和actual_user_nickname为系统
        cmsg.sender_wxid = "系统消息"
        cmsg.actual_user_id = "系统消息"
        cmsg.actual_user_nickname = "系统消息"
        
        logger.info(f"收到系统消息: ID:{cmsg.msg_id} 来自:{cmsg.from_user_id} 发送人:{cmsg.sender_wxid} 内容:{cmsg.content}")

    async def _call_api(self, endpoint, params):
        """通用API调用方法，用于直接访问WechatAPI的端点"""
        try:
            import aiohttp
            
            # 获取API配置
            api_host = conf().get("wx849_api_host", "127.0.0.1")
            api_port = conf().get("wx849_api_port", 9000)
            
            # 确定API路径前缀
            protocol_version = conf().get("wx849_protocol_version", "849")
            if protocol_version == "855" or protocol_version == "ipad":
                api_path_prefix = "/api"
            else:
                api_path_prefix = "/VXAPI"
            
            # 构建完整的API URL
            url = f"http://{api_host}:{api_port}{api_path_prefix}{endpoint}"
            
            # 发送请求
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=params) as response:
                    if response.status != 200:
                        logger.error(f"[WX849] API请求失败: {url}, 状态码: {response.status}")
                        return None
                    
                    # 解析响应
                    result = await response.json()
                    return result
        except Exception as e:
            logger.error(f"[WX849] API调用失败: {endpoint}, 错误: {e}")
            return None

    async def _send_message(self, to_user_id, content, msg_type=1):
        """发送消息的异步方法"""
        try:
            # 移除ignore_protection参数，使用正确的API参数格式
            if not to_user_id:
                logger.error("[WX849] 发送消息失败: 接收者ID为空")
                return None
                
            # 根据API文档调整参数格式
            params = {
                "ToWxid": to_user_id,
                "Content": content,
                "Type": msg_type,
                "Wxid": self.wxid,   # 发送者wxid
                "At": ""             # 空字符串表示不@任何人
            }
            
            # 使用自定义的API调用方法
            result = await self._call_api("/Msg/SendTxt", params)
            
            # 检查结果
            if result and isinstance(result, dict):
                success = result.get("Success", False)
                if not success:
                    error_msg = result.get("Message", "未知错误")
                    logger.error(f"[WX849] 发送消息API返回错误: {error_msg}")
            
            return result
        except Exception as e:
            logger.error(f"[WX849] 发送消息失败: {e}")
            return None

    async def _send_image(self, to_user_id, image_input):
        """发送图片的异步方法 (处理文件路径或BytesIO/bytes)"""
        try:
            # 检查接收者ID
            if not to_user_id:
                logger.error("[WX849] 发送图片失败: 接收者ID为空")
                return None
            
            image_base64 = None
            import base64
            
            if isinstance(image_input, str): # 如果是文件路径字符串
                if not os.path.exists(image_input):
                    logger.error(f"[WX849] 发送图片失败: 文件不存在 {image_input}")
                    return None
                with open(image_input, "rb") as f:
                    image_data = f.read()
                    image_base64 = base64.b64encode(image_data).decode('utf-8')
            elif isinstance(image_input, io.BytesIO):
                image_data = image_input.getvalue()
                image_base64 = base64.b64encode(image_data).decode('utf-8')
            elif isinstance(image_input, bytes):
                image_data = image_input
                image_base64 = base64.b64encode(image_data).decode('utf-8')
            else:
                logger.error(f"[WX849] 发送图片失败: 不支持的图片输入类型 {type(image_input)}")
                return None
            
            # 构建API参数
            params = {
                "ToWxid": to_user_id,
                "Base64": image_base64, # 修改参数名为 Base64
                "Wxid": self.wxid
            }
            
            # 调用API，修改端点为 /Msg/UploadImg
            result = await self._call_api("/Msg/UploadImg", params) 
            
            # 检查结果
            if result and isinstance(result, dict):
                success = result.get("Success", False)
                if not success:
                    error_msg = result.get("Message", "未知错误")
                    logger.error(f"[WX849] 发送图片API返回错误: {error_msg}")
            
            return result
        except Exception as e:
            logger.error(f"[WX849] 发送图片失败: {e}")
            return None

    def send(self, reply: Reply, context: Context):
        """发送消息"""
        # 获取接收者ID
        receiver = context.get("receiver")
        if not receiver:
            # 如果context中没有接收者，尝试从消息对象中获取
            msg = context.get("msg")
            if msg and hasattr(msg, "from_user_id"):
                receiver = msg.from_user_id
        
        if not receiver:
            logger.error("[WX849] 发送消息失败: 无法确定接收者ID")
            return
            
        loop = asyncio.new_event_loop()
        
        if reply.type == ReplyType.TEXT:
            reply.content = remove_markdown_symbol(reply.content)
            result = loop.run_until_complete(self._send_message(receiver, reply.content))
            if result and isinstance(result, dict) and result.get("Success", False):
                logger.info(f"[WX849] 发送文本消息成功: 接收者: {receiver}")
                if conf().get("log_level", "INFO") == "DEBUG":
                    logger.debug(f"[WX849] 消息内容: {reply.content[:50]}...")
            else:
                logger.warning(f"[WX849] 发送文本消息可能失败: 接收者: {receiver}, 结果: {result}")
        
        elif reply.type == ReplyType.ERROR or reply.type == ReplyType.INFO:
            reply.content = remove_markdown_symbol(reply.content)
            result = loop.run_until_complete(self._send_message(receiver, reply.content))
            if result and isinstance(result, dict) and result.get("Success", False):
                logger.info(f"[WX849] 发送消息成功: 接收者: {receiver}")
                if conf().get("log_level", "INFO") == "DEBUG":
                    logger.debug(f"[WX849] 消息内容: {reply.content[:50]}...")
            else:
                logger.warning(f"[WX849] 发送消息可能失败: 接收者: {receiver}, 结果: {result}")
        
        elif reply.type == ReplyType.IMAGE_URL:
            # 从网络下载图片并发送
            img_url = reply.content
            logger.debug(f"[WX849] 开始下载图片, url={img_url}")
            try:
                pic_res = requests.get(img_url, stream=True)
                # 使用临时文件保存图片
                tmp_path = os.path.join(get_appdata_dir(), f"tmp_img_{int(time.time())}.png")
                with open(tmp_path, 'wb') as f:
                    for block in pic_res.iter_content(1024):
                        f.write(block)
                
                # 使用我们的自定义方法发送图片
                result = loop.run_until_complete(self._send_image(receiver, tmp_path))
                
                if result and isinstance(result, dict) and result.get("Success", False):
                    logger.info(f"[WX849] 发送图片成功: 接收者: {receiver}")
                else:
                    logger.warning(f"[WX849] 发送图片可能失败: 接收者: {receiver}, 结果: {result}")
                
                # 删除临时文件
                try:
                    os.remove(tmp_path)
                except Exception as e:
                    logger.debug(f"[WX849] 删除临时图片文件失败: {e}")
            except Exception as e:
                logger.error(f"[WX849] 发送图片失败: {e}")
        
        elif reply.type == ReplyType.IMAGE: # 添加处理 ReplyType.IMAGE
            image_input = reply.content
            # 移除 os.path.exists 检查，交由 _send_image 处理
            # 使用我们的自定义方法发送本地图片或BytesIO
            result = loop.run_until_complete(self._send_image(receiver, image_input))
            
            if result and isinstance(result, dict) and result.get("Success", False):
                logger.info(f"[WX849] 发送图片成功: 接收者: {receiver}")
            else:
                logger.warning(f"[WX849] 发送图片可能失败: 接收者: {receiver}, 结果: {result}")
        
        else:
            logger.warning(f"[WX849] 不支持的回复类型: {reply.type}")
        
        loop.close() 

    async def _get_group_member_details(self, group_id):
        """获取群成员详情"""
        try:
            logger.debug(f"[WX849] 尝试获取群 {group_id} 的成员详情")
            
            # 检查是否已存在群成员信息，并检查是否需要更新
            # 定义群聊信息文件路径
            tmp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp")
            if not os.path.exists(tmp_dir):
                os.makedirs(tmp_dir)
            
            chatrooms_file = os.path.join(tmp_dir, 'wx849_rooms.json')
            
            # 读取现有的群聊信息（如果存在）
            chatrooms_info = {}
            if os.path.exists(chatrooms_file):
                try:
                    with open(chatrooms_file, 'r', encoding='utf-8') as f:
                        chatrooms_info = json.load(f)
                    logger.debug(f"[WX849] 已加载 {len(chatrooms_info)} 个现有群聊信息")
                except Exception as e:
                    logger.error(f"[WX849] 加载现有群聊信息失败: {str(e)}")
            
            # 检查该群聊是否已存在且成员信息是否已更新
            # 设定缓存有效期为24小时(86400秒)
            cache_expiry = 86400
            current_time = int(time.time())
            
            if (group_id in chatrooms_info and 
                "members" in chatrooms_info[group_id] and 
                len(chatrooms_info[group_id]["members"]) > 0 and
                "last_update" in chatrooms_info[group_id] and
                current_time - chatrooms_info[group_id]["last_update"] < cache_expiry):
                logger.debug(f"[WX849] 群 {group_id} 成员信息已存在且未过期，跳过更新")
                return chatrooms_info[group_id]
            
            logger.debug(f"[WX849] 群 {group_id} 成员信息不存在或已过期，开始更新")
            
            # 调用API获取群成员详情
            params = {
                "QID": group_id,  # 群ID参数
                "Wxid": self.wxid  # 自己的wxid参数
            }
            
            try:
                # 获取API配置
                api_host = conf().get("wx849_api_host", "127.0.0.1")
                api_port = conf().get("wx849_api_port", 9000)
                protocol_version = conf().get("wx849_protocol_version", "849")
                
                # 确定API路径前缀
                if protocol_version == "855" or protocol_version == "ipad":
                    api_path_prefix = "/api"
                else:
                    api_path_prefix = "/VXAPI"
                
                # 构建完整的API URL用于日志
                api_url = f"http://{api_host}:{api_port}{api_path_prefix}/Group/GetChatRoomMemberDetail"
                logger.debug(f"[WX849] 正在请求群成员详情API: {api_url}")
                logger.debug(f"[WX849] 请求参数: {json.dumps(params, ensure_ascii=False)}")
                
                # 调用API获取群成员详情
                response = await self._call_api("/Group/GetChatRoomMemberDetail", params)
                
                if not response or not isinstance(response, dict):
                    logger.error(f"[WX849] 获取群成员详情失败: 无效响应")
                    return None
                
                # 检查响应是否成功
                if not response.get("Success", False):
                    logger.error(f"[WX849] 获取群成员详情失败: {response.get('Message', '未知错误')}")
                    return None
                
                # 提取NewChatroomData
                data = response.get("Data", {})
                new_chatroom_data = data.get("NewChatroomData", {})
                
                if not new_chatroom_data:
                    logger.error(f"[WX849] 获取群成员详情失败: 响应中无NewChatroomData")
                    return None
                
                # 检查当前群聊是否已存在
                if group_id not in chatrooms_info:
                    chatrooms_info[group_id] = {
                        "chatroomId": group_id,
                        "nickName": group_id,
                        "chatRoomOwner": "",
                        "members": [],
                        "last_update": int(time.time())
                    }
                
                # 提取成员信息
                member_count = new_chatroom_data.get("MemberCount", 0)
                chat_room_members = new_chatroom_data.get("ChatRoomMember", [])
                
                # 确保是有效的成员列表
                if not isinstance(chat_room_members, list):
                    logger.error(f"[WX849] 获取群成员详情失败: ChatRoomMember不是有效的列表")
                    return None
                
                # 更新群聊成员信息
                members = []
                for member in chat_room_members:
                    if not isinstance(member, dict):
                        continue
                    
                    # 提取成员必要信息
                    member_info = {
                        "UserName": member.get("UserName", ""),
                        "NickName": member.get("NickName", ""),
                        "DisplayName": member.get("DisplayName", ""),
                        "ChatroomMemberFlag": member.get("ChatroomMemberFlag", 0),
                        "InviterUserName": member.get("InviterUserName", ""),
                        "BigHeadImgUrl": member.get("BigHeadImgUrl", ""),
                        "SmallHeadImgUrl": member.get("SmallHeadImgUrl", "")
                    }
                    
                    members.append(member_info)
                
                # 更新群聊信息
                chatrooms_info[group_id]["members"] = members
                chatrooms_info[group_id]["last_update"] = int(time.time())
                chatrooms_info[group_id]["memberCount"] = member_count
                
                # 同时更新群主信息
                for member in members:
                    if member.get("ChatroomMemberFlag") == 2049:  # 群主标志
                        chatrooms_info[group_id]["chatRoomOwner"] = member.get("UserName", "")
                        break
                
                # 保存到文件
                with open(chatrooms_file, 'w', encoding='utf-8') as f:
                    json.dump(chatrooms_info, f, ensure_ascii=False, indent=2)
                
                logger.info(f"[WX849] 已更新群聊 {group_id} 成员信息，成员数: {len(members)}")
                
                # 返回成员信息
                return new_chatroom_data
            except Exception as e:
                logger.error(f"[WX849] 获取群成员详情失败: {e}")
                logger.error(f"[WX849] 详细错误: {traceback.format_exc()}")
                return None
        except Exception as e:
            logger.error(f"[WX849] 获取群成员详情过程中出错: {e}")
            logger.error(f"[WX849] 详细错误: {traceback.format_exc()}")
            return None

    async def _get_group_name(self, group_id):
        """获取群名称"""
        try:
            logger.debug(f"[WX849] 尝试获取群 {group_id} 的名称")
            
            # 检查缓存中是否有群名
            cache_key = f"group_name_{group_id}"
            if hasattr(self, "group_name_cache") and cache_key in self.group_name_cache:
                cached_name = self.group_name_cache[cache_key]
                logger.debug(f"[WX849] 从缓存中获取群名: {cached_name}")
                
                # 检查是否需要更新群成员详情
                tmp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp")
                chatrooms_file = os.path.join(tmp_dir, 'wx849_rooms.json')
                
                need_update = True
                # 设定缓存有效期为24小时(86400秒)
                cache_expiry = 86400
                current_time = int(time.time())
                
                if os.path.exists(chatrooms_file):
                    try:
                        with open(chatrooms_file, 'r', encoding='utf-8') as f:
                            chatrooms_info = json.load(f)
                        
                        # 检查群信息是否存在且未过期
                        if (group_id in chatrooms_info and 
                            "last_update" in chatrooms_info[group_id] and 
                            current_time - chatrooms_info[group_id]["last_update"] < cache_expiry and
                            "members" in chatrooms_info[group_id] and 
                            len(chatrooms_info[group_id]["members"]) > 0):
                            logger.debug(f"[WX849] 群 {group_id} 信息已存在且未过期，跳过更新")
                            need_update = False
                    except Exception as e:
                        logger.error(f"[WX849] 检查群信息缓存时出错: {e}")
                
                # 只有需要更新时才启动线程获取群成员详情
                if need_update:
                    logger.debug(f"[WX849] 群 {group_id} 信息需要更新，启动更新线程")
                    threading.Thread(target=lambda: asyncio.run(self._get_group_member_details(group_id))).start()
                
                return cached_name
            
            # 检查文件中是否已经有群信息，且未过期
            tmp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp")
            if not os.path.exists(tmp_dir):
                os.makedirs(tmp_dir)
            
            chatrooms_file = os.path.join(tmp_dir, 'wx849_rooms.json')
            
            # 设定缓存有效期为24小时(86400秒)
            cache_expiry = 86400
            current_time = int(time.time())
            
            if os.path.exists(chatrooms_file):
                try:
                    with open(chatrooms_file, 'r', encoding='utf-8') as f:
                        chatrooms_info = json.load(f)
                    
                    # 检查群信息是否存在且未过期
                    if (group_id in chatrooms_info and 
                        "nickName" in chatrooms_info[group_id] and
                        chatrooms_info[group_id]["nickName"] and
                        chatrooms_info[group_id]["nickName"] != group_id and
                        "last_update" in chatrooms_info[group_id] and 
                        current_time - chatrooms_info[group_id]["last_update"] < cache_expiry):
                        
                        # 从文件中获取群名
                        group_name = chatrooms_info[group_id]["nickName"]
                        logger.debug(f"[WX849] 从文件缓存中获取群名: {group_name}")
                        
                        # 缓存群名
                        if not hasattr(self, "group_name_cache"):
                            self.group_name_cache = {}
                        self.group_name_cache[cache_key] = group_name
                        
                        # 检查是否需要更新群成员详情
                        need_update_members = not ("members" in chatrooms_info[group_id] and 
                                                len(chatrooms_info[group_id]["members"]) > 0)
                        
                        if need_update_members:
                            logger.debug(f"[WX849] 群 {group_id} 名称已缓存，但需要更新成员信息")
                            threading.Thread(target=lambda: asyncio.run(self._get_group_member_details(group_id))).start()
                        else:
                            logger.debug(f"[WX849] 群 {group_id} 信息已完整且未过期，无需更新")
                        
                        return group_name
                except Exception as e:
                    logger.error(f"[WX849] 从文件获取群名出错: {e}")
            
            logger.debug(f"[WX849] 群 {group_id} 信息不存在或已过期，需要从API获取")
            
            # 调用API获取群信息 - 使用群聊API
            params = {
                "QID": group_id,  # 群ID参数，正确的参数名是QID
                "Wxid": self.wxid  # 自己的wxid参数
            }
            
            try:
                # 获取API配置
                api_host = conf().get("wx849_api_host", "127.0.0.1")
                api_port = conf().get("wx849_api_port", 9000)
                protocol_version = conf().get("wx849_protocol_version", "849")
                
                # 确定API路径前缀
                if protocol_version == "855" or protocol_version == "ipad":
                    api_path_prefix = "/api"
                else:
                    api_path_prefix = "/VXAPI"
                
                # 构建完整的API URL用于日志
                api_url = f"http://{api_host}:{api_port}{api_path_prefix}/Group/GetChatRoomInfo"
                logger.debug(f"[WX849] 正在请求群信息API: {api_url}")
                logger.debug(f"[WX849] 请求参数: {json.dumps(params, ensure_ascii=False)}")  # 记录请求参数
                
                # 尝试使用群聊专用API
                group_info = await self._call_api("/Group/GetChatRoomInfo", params)
                
                # 保存群聊详情到统一的JSON文件
                try:
                    # 读取现有的群聊信息（如果存在）
                    chatrooms_info = {}
                    if os.path.exists(chatrooms_file):
                        try:
                            with open(chatrooms_file, 'r', encoding='utf-8') as f:
                                chatrooms_info = json.load(f)
                            logger.debug(f"[WX849] 已加载 {len(chatrooms_info)} 个现有群聊信息")
                        except Exception as e:
                            logger.error(f"[WX849] 加载现有群聊信息失败: {str(e)}")
                    
                    # 提取必要的群聊信息
                    if group_info and isinstance(group_info, dict):
                        # 递归函数用于查找特定key的值
                        def find_value(obj, key):
                            # 如果是字典
                            if isinstance(obj, dict):
                                # 直接检查当前字典
                                if key in obj:
                                    return obj[key]
                                # 检查带有"string"嵌套的字典
                                if key in obj and isinstance(obj[key], dict) and "string" in obj[key]:
                                    return obj[key]["string"]
                                # 递归检查字典的所有值
                                for k, v in obj.items():
                                    result = find_value(v, key)
                                    if result is not None:
                                        return result
                            # 如果是列表
                            elif isinstance(obj, list):
                                # 递归检查列表的所有项
                                for item in obj:
                                    result = find_value(item, key)
                                    if result is not None:
                                        return result
                            return None
                        
                        # 尝试提取群名称及其他信息
                        group_name = None
                        
                        # 首先尝试从NickName中获取
                        nickname_obj = find_value(group_info, "NickName")
                        if isinstance(nickname_obj, dict) and "string" in nickname_obj:
                            group_name = nickname_obj["string"]
                        elif isinstance(nickname_obj, str):
                            group_name = nickname_obj
                        
                        # 如果没找到，尝试其他可能的字段
                        if not group_name:
                            for name_key in ["ChatRoomName", "nickname", "name", "DisplayName"]:
                                name_value = find_value(group_info, name_key)
                                if name_value:
                                    if isinstance(name_value, dict) and "string" in name_value:
                                        group_name = name_value["string"]
                                    elif isinstance(name_value, str):
                                        group_name = name_value
                                    if group_name:
                                        break
                        
                        # 提取群主ID
                        owner_id = None
                        for owner_key in ["ChatRoomOwner", "chatroomowner", "Owner"]:
                            owner_value = find_value(group_info, owner_key)
                            if owner_value:
                                if isinstance(owner_value, dict) and "string" in owner_value:
                                    owner_id = owner_value["string"]
                                elif isinstance(owner_value, str):
                                    owner_id = owner_value
                                if owner_id:
                                    break
                        
                        # 检查群聊信息是否已存在
                        if group_id in chatrooms_info:
                            # 更新已有群聊信息
                            if group_name:
                                chatrooms_info[group_id]["nickName"] = group_name
                            if owner_id:
                                chatrooms_info[group_id]["chatRoomOwner"] = owner_id
                            chatrooms_info[group_id]["last_update"] = int(time.time())
                        else:
                            # 创建新群聊信息
                            chatrooms_info[group_id] = {
                                "chatroomId": group_id,
                                "nickName": group_name or group_id,
                                "chatRoomOwner": owner_id or "",
                                "members": [],
                                "last_update": int(time.time())
                            }
                        
                        # 保存到文件
                        with open(chatrooms_file, 'w', encoding='utf-8') as f:
                            json.dump(chatrooms_info, f, ensure_ascii=False, indent=2)
                        
                        logger.info(f"[WX849] 已更新群聊 {group_id} 基础信息")
                        
                        # 缓存群名
                        if group_name:
                            if not hasattr(self, "group_name_cache"):
                                self.group_name_cache = {}
                            self.group_name_cache[cache_key] = group_name
                            
                            # 异步获取群成员详情（不阻塞当前方法）
                            threading.Thread(target=lambda: asyncio.run(self._get_group_member_details(group_id))).start()
                            
                            return group_name
                    
                except Exception as save_err:
                    logger.error(f"[WX849] 保存群聊信息到文件失败: {save_err}")
                    import traceback
                    logger.error(f"[WX849] 详细错误: {traceback.format_exc()}")
                
                # 如果上面的处理没有返回群名称，再次尝试从原始数据中提取
                if group_info and isinstance(group_info, dict):
                    # 尝试从API返回中获取群名称
                    group_name = None
                    
                    # 尝试多种可能的字段名
                    possible_fields = ["NickName", "nickname", "ChatRoomName", "chatroomname", "DisplayName", "displayname"]
                    for field in possible_fields:
                        if field in group_info and group_info[field]:
                            group_name = group_info[field]
                            if isinstance(group_name, dict) and "string" in group_name:
                                group_name = group_name["string"]
                            break
                    
                    if group_name:
                        logger.debug(f"[WX849] 获取到群名称: {group_name}")
                        
                        # 缓存群名
                        if not hasattr(self, "group_name_cache"):
                            self.group_name_cache = {}
                        self.group_name_cache[cache_key] = group_name
                        
                        # 异步获取群成员详情
                        threading.Thread(target=lambda: asyncio.run(self._get_group_member_details(group_id))).start()
                        
                        return group_name
                    else:
                        logger.warning(f"[WX849] API返回成功但未找到群名称字段: {json.dumps(group_info, ensure_ascii=False)}")
                else:
                    logger.warning(f"[WX849] API返回无效数据: {group_info}")
            except Exception as e:
                # 详细记录API请求失败的错误信息
                logger.error(f"[WX849] 使用群聊API获取群名称失败: {e}")
                logger.error(f"[WX849] 详细错误: {traceback.format_exc()}")
                logger.error(f"[WX849] 请求参数: {json.dumps(params, ensure_ascii=False)}")
            
            # 如果无法获取群名，使用群ID作为名称
            logger.debug(f"[WX849] 无法获取群名称，使用群ID代替: {group_id}")
            # 缓存结果
            if not hasattr(self, "group_name_cache"):
                self.group_name_cache = {}
            self.group_name_cache[cache_key] = group_id
            
            # 尽管获取群名失败，仍然尝试获取群成员详情
            threading.Thread(target=lambda: asyncio.run(self._get_group_member_details(group_id))).start()
            
            return group_id
        except Exception as e:
            logger.error(f"[WX849] 获取群名称失败: {e}")
            logger.error(f"[WX849] 详细错误: {traceback.format_exc()}")
            return group_id

    def _compose_context(self, ctype: ContextType, content, **kwargs):
        """重写父类方法，构建消息上下文"""
        try:
            # 直接创建Context对象，确保结构正确
            context = Context()
            context.type = ctype
            context.content = content
            
            # 获取消息对象
            msg = kwargs.get('msg')
            
            # 检查是否是群聊消息
            isgroup = kwargs.get('isgroup', False)
            if isgroup and msg and hasattr(msg, 'from_user_id'):
                # 设置群组相关信息
                context["isgroup"] = True
                context["from_user_nickname"] = msg.sender_wxid  # 发送者昵称
                context["from_user_id"] = msg.sender_wxid  # 发送者ID
                context["to_user_id"] = msg.to_user_id  # 接收者ID
                context["other_user_id"] = msg.other_user_id or msg.from_user_id  # 群ID
                context["group_name"] = msg.from_user_id  # 临时使用群ID作为群名
                context["group_id"] = msg.from_user_id  # 群ID
                context["msg"] = msg  # 消息对象
                
                # 设置session_id为群ID
                context["session_id"] = msg.other_user_id or msg.from_user_id
                
                # 启动异步任务获取群名称并更新
                loop = asyncio.get_event_loop()
                try:
                    # 尝试创建异步任务获取群名
                    async def update_group_name():
                        try:
                            group_name = await self._get_group_name(msg.from_user_id)
                            if group_name:
                                context['group_name'] = group_name
                                logger.debug(f"[WX849] 更新群名称: {group_name}")
                        except Exception as e:
                            logger.error(f"[WX849] 更新群名称失败: {e}")
                    
                    # 使用已有事件循环运行更新任务
                    def run_async_task():
                        try:
                            asyncio.run(update_group_name())
                        except Exception as e:
                            logger.error(f"[WX849] 异步获取群名称任务失败: {e}")
                    
                    # 启动线程执行异步任务
                    threading.Thread(target=run_async_task).start()
                except Exception as e:
                    logger.error(f"[WX849] 创建获取群名称任务失败: {e}")
            else:
                # 私聊消息
                context["isgroup"] = False
                context["from_user_nickname"] = msg.sender_wxid if msg and hasattr(msg, 'sender_wxid') else ""
                context["from_user_id"] = msg.sender_wxid if msg and hasattr(msg, 'sender_wxid') else ""
                context["to_user_id"] = msg.to_user_id if msg and hasattr(msg, 'to_user_id') else ""
                context["other_user_id"] = None
                context["msg"] = msg
                
                # 设置session_id为发送者ID
                context["session_id"] = msg.sender_wxid if msg and hasattr(msg, 'sender_wxid') else ""

            # 添加接收者信息
            context["receiver"] = msg.from_user_id if isgroup else msg.sender_wxid
            
            # 记录原始消息类型
            context["origin_ctype"] = ctype
            
            # 添加调试日志
            logger.debug(f"[WX849] 生成Context对象: type={context.type}, content={context.content}, isgroup={context['isgroup']}, session_id={context.get('session_id', 'None')}")
            
            return context
        except Exception as e:
            logger.error(f"[WX849] 构建上下文失败: {e}")
            logger.error(f"[WX849] 详细错误: {traceback.format_exc()}")
            return None

    async def _get_chatroom_member_nickname(self, group_id, member_wxid):
        """获取群成员的昵称"""
        if not group_id or not member_wxid:
            return member_wxid
            
        try:
            # 优先从缓存获取群成员信息
            tmp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp")
            chatrooms_file = os.path.join(tmp_dir, 'wx849_rooms.json')
            
            if os.path.exists(chatrooms_file):
                with open(chatrooms_file, 'r', encoding='utf-8') as f:
                    chatrooms_info = json.load(f)
                
                if group_id in chatrooms_info and "members" in chatrooms_info[group_id]:
                    for member in chatrooms_info[group_id]["members"]:
                        if member.get("UserName") == member_wxid:
                            # 优先使用群内显示名称(群昵称)
                            if member.get("DisplayName"):
                                logger.debug(f"[WX849] 获取到成员 {member_wxid} 的群昵称: {member.get('DisplayName')}")
                                return member.get("DisplayName")
                            # 其次使用成员昵称
                            elif member.get("NickName"):
                                logger.debug(f"[WX849] 获取到成员 {member_wxid} 的昵称: {member.get('NickName')}")
                                return member.get("NickName")
            
            # 如果缓存中没有，尝试更新群成员信息
            await self._get_group_member_details(group_id)
            
            # 再次尝试从更新后的缓存中获取
            if os.path.exists(chatrooms_file):
                with open(chatrooms_file, 'r', encoding='utf-8') as f:
                    chatrooms_info = json.load(f)
                
                if group_id in chatrooms_info and "members" in chatrooms_info[group_id]:
                    for member in chatrooms_info[group_id]["members"]:
                        if member.get("UserName") == member_wxid:
                            # 优先使用群内显示名称
                            if member.get("DisplayName"):
                                logger.debug(f"[WX849] 更新后获取到成员 {member_wxid} 的群昵称: {member.get('DisplayName')}")
                                return member.get("DisplayName")
                            # 其次使用成员昵称
                            elif member.get("NickName"):
                                logger.debug(f"[WX849] 更新后获取到成员 {member_wxid} 的昵称: {member.get('NickName')}")
                                return member.get("NickName")
        except Exception as e:
            logger.error(f"[WX849] 获取群成员昵称出错: {e}")
        
        # 默认返回wxid
        return member_wxid
import asyncio
import os
import json
import time
import threading
import io
import sys
from typing import Dict, Any

import requests
from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_channel import ChatChannel
from channel.chat_message import ChatMessage
from channel.wx849.wx849_message import WX849Message  # 改为从wx849_message导入WX849Message
from common.expired_dict import ExpiredDict
from common.log import logger
from common.singleton import singleton
from common.time_check import time_checker
from common.utils import remove_markdown_symbol
from config import conf, get_appdata_dir

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
        
        # 添加过滤消息的配置
        self.ignore_mode = conf().get("wx849_ignore_mode", "None")  # None, Whitelist, Blacklist
        self.whitelist = conf().get("wx849_whitelist", [])
        self.blacklist = conf().get("wx849_blacklist", [])
        self.ignore_protection = conf().get("wx849_ignore_protection", False)

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

        # 添加登录流程 - 获取二维码并等待扫码登录
        # 创建设备名称和设备ID
        device_name = "DoW微信机器人"
        device_id = ""
        
        # 尝试获取已缓存的登录信息
        try:
            cached_info = await self.bot.get_cached_info("")
            if cached_info and "Wxid" in cached_info:
                logger.info(f"[WX849] 发现已登录的微信账号: {cached_info.get('Wxid')}")
                self.wxid = cached_info.get("Wxid")
                self.name = cached_info.get("Nickname", "")
                self.user_id = self.wxid
                logger.info(f"[WX849] 使用缓存登录, user_id: {self.user_id}, nickname: {self.name}")
                return True
        except Exception as e:
            logger.debug(f"[WX849] 获取缓存登录信息失败: {e}")
        
        try:
            # 获取登录二维码
            uuid, qr_url = await self.bot.get_qr_code(device_name, device_id, print_qr=True)
            if not uuid:
                logger.error("[WX849] 获取登录二维码失败")
                return False
                
            logger.info(f"[WX849] 请扫描二维码登录: {qr_url}")
            
            # 等待扫码登录 (最多等待120秒)
            login_timeout = 120
            while login_timeout > 0:
                try:
                    # 检查登录状态
                    login_success, login_result = await self.bot.check_login_uuid(uuid)
                    if login_success:
                        logger.info("[WX849] 登录成功")
                        
                        # 如果login_result包含用户信息，直接设置
                        if isinstance(login_result, dict) and login_result.get("acctSectResp"):
                            self.wxid = login_result.get("acctSectResp").get("userName", "")
                            self.name = login_result.get("acctSectResp").get("nickName", "")
                            self.user_id = self.wxid
                            logger.info(f"[WX849] 登录信息: user_id: {self.user_id}, nickname: {self.name}")
                        break
                except Exception as e:
                    logger.error(f"[WX849] 检查登录状态出错: {e}")
                    
                # 等待2秒后再次检查
                await asyncio.sleep(2)
                login_timeout -= 2
                logger.info(f"[WX849] 等待扫码登录中，剩余 {login_timeout} 秒...")
                
            if login_timeout <= 0:
                logger.error("[WX849] 等待扫码登录超时")
                return False
        except Exception as e:
            logger.error(f"[WX849] 登录过程出错: {e}")
            return False

        # 获取并设置个人信息
        try:
            # 如果在登录阶段已经获取到了wxid，可以跳过get_self_info
            if self.wxid and self.name:
                logger.info(f"[WX849] 已有登录信息，跳过获取个人信息, user_id: {self.user_id}, nickname: {self.name}")
                return True
                
            self_info = await self.bot.get_self_info()
            if self_info:
                # 不同版本的API可能返回不同的字段名，尝试多种可能性
                self.wxid = self_info.get("wxid", self_info.get("Wxid", self_info.get("userName", "")))
                self.name = self_info.get("nickname", self_info.get("Nickname", self_info.get("nickName", "")))
                self.user_id = self.wxid
                logger.info(f"[WX849] 登录成功, user_id: {self.user_id}, nickname: {self.name}")
                return True
            else:
                logger.error("[WX849] 获取个人信息失败")
                return False
        except UserLoggedOut:
            logger.error("[WX849] 用户未登录，无法获取个人信息")
            return False
        except Exception as e:
            logger.error(f"[WX849] 获取个人信息出错: {e}")
            return False

    async def _message_listener(self):
        """消息监听器"""
        logger.info("[WX849] 开始监听消息...")
        last_check_time = int(time.time())
        error_count = 0
        
        while self.is_running:
            try:
                # 获取新消息
                try:
                    logger.debug("[WX849] 正在获取新消息...")
                    messages = await self.bot.get_new_message()
                    # 重置错误计数
                    error_count = 0
                except Exception as e:
                    error_count += 1
                    error_msg = str(e)
                    logger.error(f"[WX849] 获取消息出错: {e}")
                    
                    # 检查是否是MIME类型错误
                    if "unexpected mimetype: text/html" in error_msg:
                        logger.info(f"[WX849] 检测到HTML响应而非JSON，尝试重新初始化连接...")
                        # 如果连续出现5次以上的错误，尝试重新初始化
                        if error_count >= 5:
                            logger.warning(f"[WX849] 连续{error_count}次获取消息失败，尝试重新初始化客户端...")
                            if await self._initialize_bot():
                                logger.info("[WX849] 客户端重新初始化成功")
                                error_count = 0
                            else:
                                logger.error("[WX849] 客户端重新初始化失败")
                    
                    await asyncio.sleep(5)  # 出错后等待一段时间再重试
                    continue
                
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
                
                # 每5分钟检查一次连接状态
                current_time = int(time.time())
                if current_time - last_check_time > 300:
                    try:
                        if not await self.bot.is_running():
                            logger.error("[WX849] WechatAPI 连接断开，尝试重新连接")
                            # 尝试重新初始化
                            if await self._initialize_bot():
                                logger.info("[WX849] 重新连接成功")
                            else:
                                logger.error("[WX849] 重新连接失败")
                    except Exception as e:
                        logger.error(f"[WX849] 检查连接状态出错: {e}")
                        # 尝试重新初始化
                        if await self._initialize_bot():
                            logger.info("[WX849] 重新连接成功")
                        else:
                            logger.error("[WX849] 重新连接失败")
                    last_check_time = current_time
                
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
            # 初始化机器人
            if await self._initialize_bot():
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
            
            # 检查是否需要忽略该消息
            if not self.should_process_message(cmsg.from_user_id, cmsg.sender_wxid):
                logger.debug(f"[WX849] 已忽略来自 {cmsg.from_user_id} 的消息")
                return
            
            # 只记录关键消息信息，减少日志输出
            if conf().get("log_level", "INFO") != "ERROR":
                logger.debug(f"[WX849] 私聊消息 - 类型: {cmsg.ctype}, ID: {cmsg.msg_id}, 内容: {cmsg.content[:20]}...")
            
            # 根据消息类型处理
            if cmsg.ctype == ContextType.VOICE and conf().get("speech_recognition") != True:
                    logger.debug("[WX849] 语音识别功能未启用，跳过处理")
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
            # 处理消息内容和类型
            self._process_message(cmsg)
            
            # 检查是否需要忽略该消息
            if not self.should_process_message(cmsg.from_user_id, cmsg.sender_wxid):
                logger.debug(f"[WX849] 已忽略来自群 {cmsg.from_user_id} 发送者 {cmsg.sender_wxid} 的消息")
                return
            
            # 只记录关键消息信息，减少日志输出
            if conf().get("log_level", "INFO") != "ERROR":
                logger.debug(f"[WX849] 群聊消息 - 类型: {cmsg.ctype}, 群ID: {cmsg.other_user_id}")
            
            # 根据消息类型处理
            if cmsg.ctype == ContextType.VOICE and conf().get("group_speech_recognition") != True:
                    logger.debug("[WX849] 群聊语音识别功能未启用，跳过处理")
                    return
            
            # 生成上下文
            context = self._compose_context(cmsg.ctype, cmsg.content, isgroup=True, msg=cmsg)
            if context:
                self.produce(context)
            else:
                logger.debug(f"[WX849] 生成群聊上下文失败，跳过处理")
        except Exception as e:
            logger.error(f"[WX849] 处理群聊消息异常: {e}")
            if conf().get("log_level", "INFO") == "DEBUG":
                import traceback
                logger.debug(f"[WX849] 异常堆栈: {traceback.format_exc()}")

    def _process_message(self, cmsg):
        """处理消息内容和类型"""
        # 根据消息类型分发处理
        if cmsg.msg_type == 1:  # 文本消息
            self._process_text_message(cmsg)
        elif cmsg.msg_type == 3:  # 图片消息
            self._process_image_message(cmsg)
        elif cmsg.msg_type == 34:  # 语音消息
            self._process_voice_message(cmsg)
        elif cmsg.msg_type == 43:  # 视频消息
            self._process_video_message(cmsg)
        elif cmsg.msg_type == 47:  # 表情消息
            self._process_emoji_message(cmsg)
        elif cmsg.msg_type == 49:  # XML消息
            self._process_xml_message(cmsg)
        elif cmsg.msg_type == 10000 or cmsg.msg_type == 10002:  # 系统消息
            self._process_system_message(cmsg)
        else:
            cmsg.ctype = ContextType.UNKNOWN
            # 如果有内容，尝试作为文本处理
            if cmsg.content and not ("<sysmsg" in cmsg.content or "\n<sysmsg" in cmsg.content):
                cmsg.ctype = ContextType.TEXT
                self._process_text_message(cmsg)
            else:
                logger.info(f"收到未知类型消息: ID:{cmsg.msg_id} 类型:{cmsg.msg_type} 来自:{cmsg.from_user_id}")

    def _process_text_message(self, cmsg):
        """处理文本消息"""
        import xml.etree.ElementTree as ET
        
        cmsg.ctype = ContextType.TEXT
        
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
        else:
            # 私聊消息
            cmsg.sender_wxid = cmsg.from_user_id
            cmsg.is_group = False
        
        # 解析@信息
        try:
            msg_source = cmsg.msg.get("MsgSource", "")
            if msg_source:
                root = ET.fromstring(msg_source)
                ats_elem = root.find("atuserlist")
                if ats_elem is not None and ats_elem.text:
                    cmsg.at_list = ats_elem.text.strip(",").split(",")
        except Exception:
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
        else:
            # 私聊消息
            cmsg.sender_wxid = cmsg.from_user_id
            cmsg.is_group = False
        
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
        
        # 输出日志
        xml_brief = cmsg.content[:50] + "..." if len(cmsg.content) > 50 else cmsg.content
        logger.info(f"收到图片消息: ID:{cmsg.msg_id} 来自:{cmsg.from_user_id} 发送人:{cmsg.sender_wxid} XML:{xml_brief}")
        
        # 可以添加异步下载图片的逻辑，如xybot.py中那样
        # 但需要在self.bot中添加相应的方法

    def _process_voice_message(self, cmsg):
        """处理语音消息"""
        import xml.etree.ElementTree as ET
        
        cmsg.ctype = ContextType.VOICE
        
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
        else:
            # 私聊消息
            cmsg.sender_wxid = cmsg.from_user_id
            cmsg.is_group = False
        
        # 解析语音信息
        try:
            root = ET.fromstring(cmsg.content)
            voice_element = root.find('voicemsg')
            if voice_element is not None:
                cmsg.voice_info = {
                    'voiceurl': voice_element.get('voiceurl'),
                    'length': voice_element.get('length')
                }
                logger.debug(f"解析语音XML成功: voiceurl={cmsg.voice_info['voiceurl']}, length={cmsg.voice_info['length']}")
        except Exception as e:
            logger.debug(f"解析语音消息失败: {e}, 内容: {cmsg.content[:100]}")
            cmsg.voice_info = {}
        
        # 输出日志
        xml_brief = cmsg.content[:50] + "..." if len(cmsg.content) > 50 else cmsg.content
        logger.info(f"收到语音消息: ID:{cmsg.msg_id} 来自:{cmsg.from_user_id} 发送人:{cmsg.sender_wxid} XML:{xml_brief}")
        
        # 可以添加异步下载语音的逻辑，如xybot.py中那样
        # 但需要在self.bot中添加相应的方法

    def _process_video_message(self, cmsg):
        """处理视频消息"""
        import xml.etree.ElementTree as ET
        
        cmsg.ctype = ContextType.VIDEO
        
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
        else:
            # 私聊消息
            cmsg.sender_wxid = cmsg.from_user_id
            cmsg.is_group = False
        
        # 输出日志
        xml_brief = cmsg.content[:50] + "..." if len(cmsg.content) > 50 else cmsg.content
        logger.info(f"收到视频消息: ID:{cmsg.msg_id} 来自:{cmsg.from_user_id} 发送人:{cmsg.sender_wxid} XML:{xml_brief}")

    def _process_emoji_message(self, cmsg):
        """处理表情消息"""
        import xml.etree.ElementTree as ET
        
        cmsg.ctype = ContextType.TEXT  # 表情消息通常也用TEXT类型
        
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
        else:
            # 私聊消息
            cmsg.sender_wxid = cmsg.from_user_id
            cmsg.is_group = False
        
        # 输出日志
        xml_brief = cmsg.content[:50] + "..." if len(cmsg.content) > 50 else cmsg.content
        logger.info(f"收到表情消息: ID:{cmsg.msg_id} 来自:{cmsg.from_user_id} 发送人:{cmsg.sender_wxid} XML:{xml_brief}")

    def _process_xml_message(self, cmsg):
        """处理XML消息"""
        import xml.etree.ElementTree as ET
        
        # 先默认设置为XML类型
        cmsg.ctype = ContextType.XML
        
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
        else:
            # 私聊消息
            cmsg.sender_wxid = cmsg.from_user_id
            cmsg.is_group = False
            
        # 解析XML内容，识别特殊类型
        try:
            if "<appmsg" in cmsg.content:
                root = ET.fromstring(cmsg.content)
                appmsg = root.find("appmsg")
                if appmsg is not None:
                    type_element = appmsg.find("type")
                    type_value = int(type_element.text) if type_element is not None and type_element.text.isdigit() else 0
                    
                    if type_value == 5:  # 链接卡片
                        cmsg.ctype = ContextType.LINK
                        title = appmsg.find("title").text if appmsg.find("title") is not None else ""
                        url = appmsg.find("url").text if appmsg.find("url") is not None else ""
                        desc = appmsg.find("des").text if appmsg.find("des") is not None else ""
                        cmsg.link_info = {
                            "title": title,
                            "url": url,
                            "desc": desc
                        }
                        cmsg.content = f"{title}\n{url}"
                        logger.info(f"收到链接消息: ID:{cmsg.msg_id} 来自:{cmsg.from_user_id} 发送人:{cmsg.sender_wxid} 标题:{title}")
                        return
                    elif type_value == 6:  # 文件
                        cmsg.ctype = ContextType.FILE
                        title = appmsg.find("title").text if appmsg.find("title") is not None else ""
                        file_ext = None
                        file_size = None
                        
                        try:
                            appattach = appmsg.find("appattach")
                            if appattach is not None:
                                file_ext = appattach.find("fileext").text if appattach.find("fileext") is not None else ""
                                totallen_elem = appattach.find("totallen")
                                file_size = totallen_elem.text if totallen_elem is not None else "0"
                                attach_id = appattach.find("attachid").text if appattach.find("attachid") is not None else ""
                                cmsg.file_info = {
                                    "filename": title,
                                    "fileext": file_ext,
                                    "filesize": file_size,
                                    "attachid": attach_id
                                }
                        except Exception as e:
                            logger.error(f"解析文件附件失败: {e}")
                        
                        logger.info(f"收到文件消息: ID:{cmsg.msg_id} 来自:{cmsg.from_user_id} 发送人:{cmsg.sender_wxid} 文件名:{title}")
                        return
                    elif type_value == 33:  # 小程序
                        cmsg.ctype = ContextType.MINIAPP
                        title = appmsg.find("title").text if appmsg.find("title") is not None else ""
                        
                        try:
                            weappinfo = appmsg.find("weappinfo")
                            if weappinfo is not None:
                                pagepath = weappinfo.find("pagepath").text if weappinfo.find("pagepath") is not None else ""
                                cmsg.miniapp_info = {
                                    "title": title,
                                    "pagepath": pagepath
                                }
                        except Exception as e:
                            logger.error(f"解析小程序信息失败: {e}")
                        
                        logger.info(f"收到小程序消息: ID:{cmsg.msg_id} 来自:{cmsg.from_user_id} 发送人:{cmsg.sender_wxid} 小程序:{title}")
                        return
                    elif type_value == 57:  # 引用消息
                        self._process_quote_message(cmsg)
                        return
        except Exception as e:
            logger.debug(f"[WX849] 解析XML消息失败: {e}")
        
        # 如果没有被识别为特殊类型，就当作普通XML消息处理
        brief_content = cmsg.content[:50] + "..." if len(cmsg.content) > 50 else cmsg.content
        logger.info(f"收到XML消息: ID:{cmsg.msg_id} 来自:{cmsg.from_user_id} 发送人:{cmsg.sender_wxid} XML:{brief_content}")

    def _process_quote_message(self, cmsg):
        """处理引用消息"""
        import xml.etree.ElementTree as ET
        
        cmsg.ctype = ContextType.QUOTE
        quote_message = {}
        
        try:
            root = ET.fromstring(cmsg.content)
            appmsg = root.find("appmsg")
            text = appmsg.find("title").text if appmsg.find("title") is not None else ""
            refermsg = appmsg.find("refermsg")
            
            if refermsg is not None:
                quote_message["msg_type"] = int(refermsg.find("type").text) if refermsg.find("type") is not None else 0
                
                if quote_message["msg_type"] == 1:  # 文本消息
                    quote_message["msg_id"] = refermsg.find("svrid").text if refermsg.find("svrid") is not None else ""
                    quote_message["from_user"] = refermsg.find("chatusr").text if refermsg.find("chatusr") is not None else ""
                    quote_message["to_user"] = refermsg.find("fromusr").text if refermsg.find("fromusr") is not None else ""
                    quote_message["nickname"] = refermsg.find("displayname").text if refermsg.find("displayname") is not None else ""
                    quote_message["content"] = refermsg.find("content").text if refermsg.find("content") is not None else ""
                    quote_message["create_time"] = refermsg.find("createtime").text if refermsg.find("createtime") is not None else ""
                
                elif quote_message["msg_type"] == 49:  # 引用XML消息
                    quote_message["msg_id"] = refermsg.find("svrid").text if refermsg.find("svrid") is not None else ""
                    quote_message["from_user"] = refermsg.find("chatusr").text if refermsg.find("chatusr") is not None else ""
                    quote_message["to_user"] = refermsg.find("fromusr").text if refermsg.find("fromusr") is not None else ""
                    quote_message["nickname"] = refermsg.find("displayname").text if refermsg.find("displayname") is not None else ""
                    quote_message["raw_content"] = refermsg.find("content").text if refermsg.find("content") is not None else ""
                    quote_message["create_time"] = refermsg.find("createtime").text if refermsg.find("createtime") is not None else ""
                    
                    # 进一步解析引用的XML内容
                    try:
                        quote_root = ET.fromstring(quote_message["raw_content"])
                        quote_appmsg = quote_root.find("appmsg")
                        if quote_appmsg is not None:
                            quote_message["content"] = quote_appmsg.find("title").text if quote_appmsg.find("title") is not None else ""
                            quote_message["description"] = quote_appmsg.find("des").text if quote_appmsg.find("des") is not None else ""
                            quote_message["url"] = quote_appmsg.find("url").text if quote_appmsg.find("url") is not None else ""
                    except:
                        quote_message["content"] = "无法解析的引用内容"
            
            cmsg.content = text
            cmsg.quote_info = quote_message
            
            # 输出日志
            quoted_content = quote_message.get("content", "")[:30]
            if len(quote_message.get("content", "")) > 30:
                quoted_content += "..."
            
            logger.info(f"收到引用消息: ID:{cmsg.msg_id} 来自:{cmsg.from_user_id} 发送人:{cmsg.sender_wxid} 内容:{cmsg.content} 引用:{quoted_content}")
        
        except Exception as e:
            logger.error(f"解析引用消息失败: {e}, 内容: {cmsg.content[:100]}")
            cmsg.ctype = ContextType.TEXT  # 解析失败时作为普通文本处理

    def _process_system_message(self, cmsg):
        """处理系统消息"""
        import xml.etree.ElementTree as ET
        
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
                    
                    # 日志输出
                    logger.info(f"收到拍一拍消息: ID:{cmsg.msg_id} 来自:{cmsg.from_user_id} 发送人:{cmsg.sender_wxid} 拍者:{patter} 被拍:{patted} 后缀:{pat_suffix}")
                    return
            except Exception as e:
                logger.debug(f"[WX849] 解析拍一拍消息失败: {e}")
        
        # 如果不是特殊系统消息，按普通系统消息处理
        cmsg.ctype = ContextType.SYSTEM
        logger.info(f"收到系统消息: ID:{cmsg.msg_id} 来自:{cmsg.from_user_id} 内容:{cmsg.content}")

    def should_process_message(self, from_wxid, sender_wxid):
        """检查是否应该处理该消息（基于白名单/黑名单）"""
        # 过滤公众号消息（公众号wxid通常以gh_开头）
        if sender_wxid and isinstance(sender_wxid, str) and sender_wxid.startswith('gh_'):
            logger.debug(f"忽略公众号消息: {sender_wxid}")
            return False
        if from_wxid and isinstance(from_wxid, str) and from_wxid.startswith('gh_'):
            logger.debug(f"忽略公众号消息: {from_wxid}")
            return False

        # 过滤微信团队和系统通知
        system_accounts = [
            'weixin',  # 微信团队
            'filehelper',  # 文件传输助手
            'fmessage',  # 朋友推荐通知
            'medianote',  # 语音记事本
            'floatbottle',  # 漂流瓶
            'qmessage',  # QQ离线消息
            'qqmail',  # QQ邮箱提醒
            'tmessage',  # 腾讯新闻
            'weibo',  # 微博推送
            'newsapp',  # 新闻推送
            'notification_messages',  # 服务通知
            'helper_entry',  # 新版微信运动
            'mphelper',  # 公众号助手
            'brandsessionholder',  # 公众号消息
            'weixinreminder',  # 微信提醒
            'officialaccounts',  # 公众平台
        ]

        # 检查是否是系统账号
        for account in system_accounts:
            if (sender_wxid and isinstance(sender_wxid, str) and sender_wxid == account) or \
               (from_wxid and isinstance(from_wxid, str) and from_wxid == account):
                logger.debug(f"忽略系统账号消息: {sender_wxid or from_wxid}")
                return False

        # 检测其他特殊账号特征
        # 微信支付相关通知
        if (sender_wxid and isinstance(sender_wxid, str) and 'wxpay' in sender_wxid) or \
           (from_wxid and isinstance(from_wxid, str) and 'wxpay' in from_wxid):
            logger.debug(f"忽略微信支付相关消息: {sender_wxid or from_wxid}")
            return False

        # 腾讯游戏相关通知
        if (sender_wxid and isinstance(sender_wxid, str) and ('tencent' in sender_wxid.lower() or 'game' in sender_wxid.lower())) or \
           (from_wxid and isinstance(from_wxid, str) and ('tencent' in from_wxid.lower() or 'game' in from_wxid.lower())):
            logger.debug(f"忽略腾讯游戏相关消息: {sender_wxid or from_wxid}")
            return False

        # 微信官方账号通常包含"service"或"official"
        if (sender_wxid and isinstance(sender_wxid, str) and ('service' in sender_wxid.lower() or 'official' in sender_wxid.lower())) or \
           (from_wxid and isinstance(from_wxid, str) and ('service' in from_wxid.lower() or 'official' in from_wxid.lower())):
            logger.debug(f"忽略官方服务账号消息: {sender_wxid or from_wxid}")
            return False

        # 检查白名单/黑名单
        is_group = from_wxid and isinstance(from_wxid, str) and from_wxid.endswith("@chatroom")

        if self.ignore_mode == "Whitelist":
            if is_group:
                # 群聊消息：群ID在白名单中或发送者ID在白名单中
                logger.debug(f"白名单检查: 群ID={from_wxid}, 发送者ID={sender_wxid}")
                return sender_wxid in self.whitelist or from_wxid in self.whitelist
            else:
                # 私聊消息：发送者ID在白名单中
                return sender_wxid in self.whitelist
        elif self.ignore_mode == "Blacklist":
            if is_group:
                # 群聊消息：群ID不在黑名单中且发送者ID不在黑名单中
                return (from_wxid not in self.blacklist) and (sender_wxid not in self.blacklist)
            else:
                # 私聊消息：发送者ID不在黑名单中
                return sender_wxid not in self.blacklist
        else:
            # 默认处理所有消息
            return True

    async def _send_message(self, to_user_id, content, msg_type=1):
        """发送消息的异步方法"""
        try:
            result = await self.bot.send_text(to_user_id, content)
            return result
        except Exception as e:
            logger.error(f"[WX849] 发送消息失败: {e}")
            return None

    def send(self, reply: Reply, context: Context):
        """发送消息"""
        receiver = context.get("receiver")
        loop = asyncio.new_event_loop()
        
        if reply.type == ReplyType.TEXT:
            reply.content = remove_markdown_symbol(reply.content)
            result = loop.run_until_complete(self._send_message(receiver, reply.content))
            logger.info(f"[WX849] 发送文本消息: {reply.content}, 接收者: {receiver}, 结果: {result}")
        
        elif reply.type == ReplyType.ERROR or reply.type == ReplyType.INFO:
            reply.content = remove_markdown_symbol(reply.content)
            result = loop.run_until_complete(self._send_message(receiver, reply.content))
            logger.info(f"[WX849] 发送消息: {reply.content}, 接收者: {receiver}, 结果: {result}")
        
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
                
                # 发送图片
                result = loop.run_until_complete(self.bot.send_image(receiver, tmp_path))
                logger.info(f"[WX849] 发送图片: {img_url}, 接收者: {receiver}, 结果: {result}")
                
                # 删除临时文件
                try:
                    os.remove(tmp_path)
                except:
                    pass
            except Exception as e:
                logger.error(f"[WX849] 发送图片失败: {e}")
        
        else:
            logger.warning(f"[WX849] 不支持的回复类型: {reply.type}")
        
        loop.close() 
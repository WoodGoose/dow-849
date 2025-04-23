try:
    # 尝试使用相对导入
    from ..errors import *
except ImportError:
    # 回退到绝对导入
    from WechatAPI.errors import *
from .base import WechatAPIClientBase, Proxy, Section
from .chatroom import ChatroomMixin
from .friend import FriendMixin
from .hongbao import HongBaoMixin
from .login import LoginMixin
from .message import MessageMixin
from .protect import protector
from .tool import ToolMixin
from .tool_extension import ToolExtensionMixin
from .user import UserMixin
from .pyq import PyqMixin
from typing import Union
import os
import time
from loguru import logger  # 导入日志记录器

class WechatAPIClient(LoginMixin, MessageMixin, FriendMixin, ChatroomMixin, UserMixin,
                      ToolMixin, ToolExtensionMixin, HongBaoMixin, PyqMixin):

    # 这里都是需要结合多个功能的方法
    
    def __init__(self, ip: str, port: int):
        super().__init__(ip, port)
        # 添加消息同步所需的属性
        self._last_key_buf = ""
        self._continue_flag = 0
        self._sync_count = 0

    async def send_at_message(self, wxid: str, content: str, at: list[str]) -> tuple[int, int, int]:
        """发送@消息

        Args:
            wxid (str): 接收人
            content (str): 消息内容
            at (list[str]): 要@的用户ID列表

        Returns:
            tuple[int, int, int]: 包含以下三个值的元组:
                - ClientMsgid (int): 客户端消息ID
                - CreateTime (int): 创建时间
                - NewMsgId (int): 新消息ID

        Raises:
            UserLoggedOut: 用户未登录时抛出
            BanProtection: 新设备登录4小时内操作时抛出
        """
        if not self.wxid:
            raise UserLoggedOut("请先登录")
        elif not self.ignore_protect and protector.check(14400):
            raise BanProtection("风控保护: 新设备登录后4小时内请挂机")

        output = ""
        for id in at:
            nickname = await self.get_nickname(id)
            output += f"@{nickname}\u2005"

        output += content

        return await self.send_text_message(wxid, output, at)
        
    async def get_self_info(self) -> dict:
        """获取当前登录用户的信息

        Returns:
            dict: 用户信息字典，包含wxid、nickname等信息

        Raises:
            UserLoggedOut: 未登录时抛出
        """
        # 调用已有的get_profile方法获取用户信息
        return await self.get_profile()
        
    async def get_new_message(self) -> list:
        """获取新消息

        Returns:
            list: 新消息列表，如果没有新消息则返回空列表

        Raises:
            UserLoggedOut: 未登录时抛出
            根据error_handler处理错误
        """
        if not self.wxid:
            raise UserLoggedOut("请先登录")
            
        import aiohttp
        
        async with aiohttp.ClientSession() as session:
            # 使用正确的参数调用 Sync 接口
            # Scene=0 适用于消息同步，根据KeyBuf持续获取新消息
            json_param = {"Wxid": self.wxid, "Scene": 0, "Synckey": self._last_key_buf}
            logger.debug(f"[WX849 API] 调用Sync接口，参数: {json_param}")
            response = await session.post(f'http://{self.ip}:{self.port}{self.api_path_prefix}/Msg/Sync', json=json_param)
            json_resp = await response.json()
            
            # 记录返回数据的简要信息（避免日志过大）
            logger.debug(f"[WX849 API] Sync 接口返回状态: {json_resp.get('Success')}")
            
            if json_resp.get("Success"):
                data = json_resp.get("Data", {})
                
                # 保存 KeyBuf 用于下次请求
                if "KeyBuf" in data and "buffer" in data["KeyBuf"]:
                    self._last_key_buf = data["KeyBuf"]["buffer"]
                    logger.debug(f"[WX849 API] 保存新的 KeyBuf，长度: {len(self._last_key_buf)}")
                
                # 保存 ContinueFlag
                if "ContinueFlag" in data:
                    self._continue_flag = data["ContinueFlag"]
                    logger.debug(f"[WX849 API] 设置 ContinueFlag: {self._continue_flag}")
                
                # 处理 AddMsgs 数组中的消息
                if "AddMsgs" in data and isinstance(data["AddMsgs"], list):
                    messages = []
                    for msg in data["AddMsgs"]:
                        # 处理每条消息，格式化为统一的格式
                        processed_msg = self._process_message(msg)
                        if processed_msg:
                            messages.append(processed_msg)
                    
                    logger.info(f"[WX849 API] 收到 {len(messages)} 条消息")
                    return messages
                else:
                    logger.debug("[WX849 API] 没有新消息")
                    return []
            else:
                # 返回空列表而不是抛出异常，使程序更健壮
                logger.warning(f"[WX849 API] 请求不成功: {json_resp.get('Message', '未知错误')}")
                return []
    
    def _process_message(self, msg) -> dict:
        """处理单条消息，将其转换为统一格式
        
        Args:
            msg (dict): 原始消息数据
            
        Returns:
            dict: 处理后的消息
        """
        try:
            # 提取基本信息
            processed = {}
            
            # 处理消息ID
            processed["msgid"] = msg.get("MsgId", 0)
            
            # 处理发送者和接收者
            from_user = msg.get("FromUserName", {}).get("string", "")
            to_user = msg.get("ToUserName", {}).get("string", "")
            processed["fromUserName"] = from_user
            processed["toUserName"] = to_user
            
            # 判断是否是群消息
            is_group = False
            if from_user and from_user.endswith("@chatroom"):
                is_group = True
                processed["roomId"] = from_user
                
                # 尝试提取群内发送者信息
                content = msg.get("Content", {}).get("string", "")
                if ":" in content:
                    sender_id, actual_content = content.split(":", 1)
                    processed["senderId"] = sender_id
                    processed["content"] = actual_content.strip()
                else:
                    processed["content"] = content
            else:
                processed["senderId"] = from_user
                processed["content"] = msg.get("Content", {}).get("string", "")
            
            # 处理消息类型
            processed["type"] = msg.get("MsgType", 0)
            
            # 处理时间戳
            processed["timestamp"] = msg.get("CreateTime", int(time.time()))
            
            # 处理新消息ID
            processed["newMsgId"] = msg.get("NewMsgId", 0)
            
            logger.debug(f"[WX849 API] 处理消息: {processed['msgid']}, 类型: {processed['type']}")
            return processed
        except Exception as e:
            logger.error(f"[WX849 API] 处理消息出错: {e}")
            return None
        
    async def send_text(self, wxid: str, content: str) -> tuple[int, int, int]:
        """发送文本消息的别名

        Args:
            wxid (str): 接收人wxid
            content (str): 消息内容

        Returns:
            tuple[int, int, int]: 返回(ClientMsgid, CreateTime, NewMsgId)

        Raises:
            UserLoggedOut: 未登录时抛出
            BanProtection: 登录新设备后4小时内操作
            根据error_handler处理错误
        """
        # 调用已有的send_text_message方法
        return await self.send_text_message(wxid, content)
        
    async def send_image(self, wxid: str, image: Union[str, bytes, os.PathLike]) -> dict:
        """发送图片消息的别名

        Args:
            wxid (str): 接收人wxid
            image (str, byte, os.PathLike): 图片，支持base64字符串，图片byte，图片路径

        Returns:
            dict: 返回完整的响应结果

        Raises:
            UserLoggedOut: 未登录时抛出
            BanProtection: 登录新设备后4小时内操作
            根据error_handler处理错误
        """
        # 调用已有的send_image_message方法
        return await self.send_image_message(wxid, image) 
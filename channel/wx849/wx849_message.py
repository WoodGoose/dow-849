import os
import time
import json
import xml.etree.ElementTree as ET
from typing import Dict, Any

from bridge.context import ContextType
from channel.chat_message import ChatMessage
from config import conf

class WX849Message(ChatMessage):
    """
    wx849 消息处理类 - 简化版，无日志输出
    """
    def __init__(self, msg: Dict[str, Any], is_group: bool = False):
        super().__init__(msg)
        self.msg = msg
        
        # 提取消息基本信息
        self.msg_id = msg.get("msgid", msg.get("MsgId", msg.get("id", "")))
        if not self.msg_id:
            self.msg_id = f"msg_{int(time.time())}_{hash(str(msg))}"
        
        self.create_time = msg.get("timestamp", msg.get("CreateTime", msg.get("createTime", int(time.time()))))
        self.is_group = is_group
        
        # 提取发送者和接收者ID
        self.from_user_id = self._get_string_value(msg.get("fromUserName", msg.get("FromUserName", "")))
        self.to_user_id = self._get_string_value(msg.get("toUserName", msg.get("ToUserName", "")))
        
        # 提取消息内容
        self.content = self._get_string_value(msg.get("content", msg.get("Content", "")))
        
        # 获取消息类型
        self.msg_type = msg.get("type", msg.get("Type", msg.get("MsgType", 0)))
        
        # 初始化其他字段
        self.sender_wxid = ""  # 实际发送者ID
        self.at_list = []      # 被@的用户列表
        self.ctype = ContextType.UNKNOWN
    
    def _get_string_value(self, value):
        """确保值为字符串类型"""
        if isinstance(value, dict):
            return value.get("string", "")
        return str(value) if value is not None else ""
    
    # 以下是公开接口方法，提供给外部使用
    def get_content(self):
        """获取消息内容"""
        return self.content
    
    def get_type(self):
        """获取消息类型"""
        return self.ctype
    
    def get_msg_id(self):
        """获取消息ID"""
        return self.msg_id
    
    def get_create_time(self):
        """获取消息创建时间"""
        return self.create_time
    
    def get_from_user_id(self):
        """获取原始发送者ID"""
        return self.from_user_id
    
    def get_sender_id(self):
        """获取处理后的实际发送者ID（群聊中特别有用）"""
        return self.sender_wxid or self.from_user_id
    
    def get_to_user_id(self):
        """获取接收者ID"""
        return self.to_user_id
    
    def get_at_list(self):
        """获取被@的用户列表"""
        return self.at_list
    
    def is_at(self, wxid):
        """检查指定用户是否被@"""
        return wxid in self.at_list
    
    def is_group_message(self):
        """判断是否为群消息"""
        return self.is_group 
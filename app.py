"""
    @Author: ImYrS Yang
    @Date: 2023/2/10
    @Copyright: ImYrS Yang
    @Description:
"""

import logging
from os import environ
from sys import argv
from typing import NoReturn, Optional
import json
import argparse

from configobj import ConfigObj
import requests

from modules import dingtalk, serverchan, pushdeer, telegram, pushplus, smtp, feishu
import github


class SignIn:
    """
    签到
    """

    def __init__(
            self,
            config: ConfigObj | dict,
            refresh_token: str,
    ):
        """
        初始化

        :param config: 配置文件, ConfigObj 对象或字典
        :param refresh_token: refresh_token
        """
        self.config = config
        self.refresh_token = refresh_token
        self.hide_refresh_token = self.__hide_refresh_token()
        self.access_token = None
        self.new_refresh_token = None
        self.phone = None
        self.signin_count = 0
        self.signin_reward = None
        self.error = None

    def __hide_refresh_token(self) -> str:
        """
        隐藏 refresh_token

        :return: 隐藏后的 refresh_token
        """
        try:
            return self.refresh_token[:4] + '*' * len(self.refresh_token[4:-4]) + self.refresh_token[-4:]
        except IndexError:
            return self.refresh_token

    def __get_access_token(self, retry: bool = False) -> bool:
        """
        获取 access_token

        :param retry: 是否重试
        :return: 是否成功
        """
        try:
            data = requests.post(
                'https://auth.aliyundrive.com/v2/account/token',
                json={
                    'grant_type': 'refresh_token',
                    'refresh_token': self.refresh_token,
                }
            ).json()
        except requests.RequestException as e:
            logging.error(f'[{self.hide_refresh_token}] 获取 access token 请求失败: {e}')
            if not retry:
                logging.info(f'[{self.hide_refresh_token}] 正在重试...')
                return self.__get_access_token(retry=True)

            self.error = e
            return False

        try:
            if data['code'] in [
                'RefreshTokenExpired', 'InvalidParameter.RefreshToken',
            ]:
                logging.error(f'[{self.hide_refresh_token}] 获取 access token 失败, 可能是 refresh token 无效.')
                self.error = data
                return False
        except KeyError:
            pass

        try:
            self.access_token = data['access_token']
            self.new_refresh_token = data['refresh_token']
            self.phone = data['user_name']
        except KeyError:
            logging.error(f'[{self.hide_refresh_token}] 获取 access token 失败, 参数缺失: {data}')
            self.error = f'获取 access token 失败, 参数缺失: {data}'
            return False

        return True

    def __sign_in(self, retry: bool = False) -> NoReturn:
        """
        签到函数

        :return:
        """
        try:
            data = requests.post(
                'https://member.aliyundrive.com/v1/activity/sign_in_list',
                params={'_rx-s': 'mobile'},
                headers={'Authorization': f'Bearer {self.access_token}'},
                json={'isReward': True},
            ).json()
            logging.debug(str(data))
        except requests.RequestException as e:
            logging.error(f'[{self.phone}] 签到请求失败: {e}')
            if not retry:
                logging.info(f'[{self.phone}] 正在重试...')
                return self.__sign_in(retry=True)

            self.error = e
            return False

        if 'success' not in data:
            logging.error(f'[{self.phone}] 签到失败, 错误信息: {data}')
            self.error = data
            return

        current_day = None
        for i, day in enumerate(data['result']['signInLogs']):
            if day['status'] == 'miss':
                current_day = data['result']['signInLogs'][i - 1]
                break

        reward = (
            '无奖励'
            if not current_day['isReward']
            else f'获得 {current_day["reward"]["name"]} {current_day["reward"]["description"]}'
        )

        self.signin_count = data['result']['signInCount']
        self.signin_reward = reward

        logging.info(f'[{self.phone}] 签到成功, 本月累计签到 {self.signin_count} 天.')
        logging.info(f'[{self.phone}] 本次签到{reward}')

    def __generate_result(self) -> dict:
        """
        获取签到结果

        :return: 签到结果
        """
        user = self.phone or self.hide_refresh_token
        text = (
            f'[{user}] 签到成功, 本月累计签到 {self.signin_count} 天.\n本次签到{self.signin_reward}'
            if self.signin_count
            else f'[{user}] 签到失败\n{json.dumps(str(self.error), indent=2, ensure_ascii=False)}'
        )

        text_html = (
            f'<code>{user}</code> 签到成功, 本月累计签到 {self.signin_count} 天.\n本次签到{self.signin_reward}'
            if self.signin_count
            else (
                f'<code>{user}</code> 签到失败\n'
                f'<code>{json.dumps(str(self.error), indent=2, ensure_ascii=False)}</code>'
            )
        )

        return {
            'success': True if self.signin_count else False,
            'user': self.phone or self.hide_refresh_token,
            'refresh_token': self.new_refresh_token or self.refresh_token,
            'count': self.signin_count,
            'reward': self.signin_reward,
            'text': text,
            'text_html': text_html,
        }

    def run(self) -> dict:
        """
        运行签到

        :return: 签到结果
        """
        result = self.__get_access_token()

        if result:
            self.__sign_in()

        return self.__generate_result()


def push(
        config: ConfigObj | dict,
        content: str,
        content_html: str,
        title: Optional[str] = None,
) -> NoReturn:
    """
    推送签到结果

    :param config: 配置文件, ConfigObj 对象或字典
    :param content: 推送内容
    :param content_html: 推送内容, HTML 格式
    :param title: 推送标题

    :return:
    """
    configured_push_types = [
        i.lower().strip()
        for i in (
            [config['push_types']]
            if type(config['push_types']) == str
            else config['push_types']
        )
    ]

    for push_type, pusher in {
        'dingtalk': dingtalk,
        'serverchan': serverchan,
        'pushdeer': pushdeer,
        'telegram': telegram,
        'pushplus': pushplus,
        'smtp': smtp,
        'feishu': feishu,
    }.items():
        if push_type in configured_push_types:
            pusher.push(config, content, content_html, title)


def init_logger(debug: Optional[bool] = False) -> NoReturn:
    """
    初始化日志系统

    :return:
    """
    log = logging.getLogger()
    log.setLevel(logging.DEBUG)
    log_format = logging.Formatter(
        '%(asctime)s - %(filename)s:%(lineno)d - %(levelname)s: %(message)s'
    )

    # Console
    ch = logging.StreamHandler()
    log.setLevel(logging.DEBUG if debug else logging.INFO)
    ch.setFormatter(log_format)
    log.addHandler(ch)

    # Log file
    log_name = 'aliyun_auto_signin.log'
    fh = logging.FileHandler(log_name, mode='a', encoding='utf-8')
    log.setLevel(logging.DEBUG if debug else logging.INFO)
    fh.setFormatter(log_format)
    log.addHandler(fh)


def get_config_from_env() -> Optional[dict]:
    """
    从环境变量获取配置

    :return: 配置字典, 配置缺失返回 None
    """
    try:
        refresh_tokens = environ['REFRESH_TOKENS'] or ''
        push_types = environ['PUSH_TYPES'] or ''

        return {
            'refresh_tokens': refresh_tokens.split(','),
            'push_types': push_types.split(','),
            'serverchan_send_key': environ['SERVERCHAN_SEND_KEY'],
            'telegram_endpoint': 'https://api.telegram.org',
            'telegram_bot_token': environ['TELEGRAM_BOT_TOKEN'],
            'telegram_chat_id': environ['TELEGRAM_CHAT_ID'],
            'telegram_proxy': None,
            'pushplus_token': environ['PUSHPLUS_TOKEN'],
            'smtp_host': environ['SMTP_HOST'],
            'smtp_port': environ['SMTP_PORT'],
            'smtp_tls': environ['SMTP_TLS'],
            'smtp_user': environ['SMTP_USER'],
            'smtp_password': environ['SMTP_PASSWORD'],
            'smtp_sender': environ['SMTP_SENDER'],
            'smtp_receiver': environ['SMTP_RECEIVER'],
            'feishu_webhook': environ['FEISHU_WEBHOOK'],
        }
    except KeyError as e:
        logging.error(f'环境变量 {e} 缺失.')
        return None


def reward_code(token: str, code: str) -> Optional[str]:
    """
    兑换福利码

    :param token: access token
    :param code: 福利码
    :return: 兑换结果, None 表示福利码已兑换
    """
    try:
        request = requests.post(
            'https://member.aliyundrive.com/v1/users/rewards',
            headers={'Authorization': token},
            json={'code': code},
        )
    except requests.exceptions.RequestException as e:
        logging.error(f'兑换福利码时发生请求错误: {e}')
        return '兑换福利码时发生请求错误'

    data = request.json()

    if 'success' not in data:
        return f'兑换福利码发生错误: {data["message"]}'

    if data['success']:
        return f'兑换福利码成功: {data["result"]["message"]}'

    else:
        if data['code'] == '30009':
            return None

        return f'兑换福利码失败: {data["message"]}'


def get_args() -> argparse.Namespace:
    """
    获取命令行参数

    :return: 命令行参数
    """
    parser = argparse.ArgumentParser(description='阿里云盘自动签到')

    parser.add_argument('--action', '-a', help='由 GitHub Actions 调用', action='store_true', default=False)
    parser.add_argument('--debug', '-d', help='调试模式', action='store_true', default=False)

    return parser.parse_args()


def main():
    """
    主函数

    :return:
    """
    environ['NO_PROXY'] = '*'  # 禁止代理

    # 旧版本兼容
    if 'action' in argv:
        by_action = True
        debug = False
    else:
        args = get_args()
        by_action = args.action
        debug = args.debug

    init_logger(debug)  # 初始化日志系统

    # 获取配置
    config = (
        get_config_from_env()
        if by_action
        else ConfigObj('config.ini', encoding='UTF8')
    )

    if not config:
        logging.error('获取配置失败.')
        return

    # 获取所有 refresh token 指向用户
    users = (
        [config['refresh_tokens']]
        if type(config['refresh_tokens']) == str
        else config['refresh_tokens']
    )

    results = []
    rewards = []

    for user in users:
        signin = SignIn(config=config, refresh_token=user)
        results.append(signin.run())

        # 阿里云盘两周年
        if not signin.access_token:
            continue

        reward = reward_code(signin.access_token, '阿里云盘两周年')
        reward = '已经兑换过这个福利码了.' if reward is None else reward
        reward = f'[{signin.phone}] {reward}'
        rewards.append(reward)

    # 合并推送
    text = '\n\n'.join([i['text'] for i in results])
    text_html = '\n\n'.join([i['text_html'] for i in results])

    push(config, text, text_html, '阿里云盘签到')

    # 阿里云盘两周年推送
    if rewards:
        text = '\n\n'.join(rewards)
        text += (
            '\n\n该功能由 阿里云盘自动签到 https://github.com/ImYrS/aliyun-auto-signin 提供.\n'
            '用于尝试自动兑换 500G 福利码, 两周年活动结束后本功能将被移除.\n'
            '如果这个项目帮助到了你, 欢迎给我一个 Star 来支持我持续维护和更新.'
        )
        text_html = text

        push(config, text, text_html, '阿里云盘两周年')

    # 更新 refresh token
    new_users = [i['refresh_token'] for i in results]

    if not by_action:
        config['refresh_tokens'] = ','.join(new_users)
    else:
        try:
            github.update_secret('REFRESH_TOKENS', ','.join(new_users))
        except Exception as e:
            err = f'Action 更新 Github Secrets 失败: {e}'
            logging.error(err)
            push(config, err, err, '阿里云盘签到')


if __name__ == '__main__':
    main()

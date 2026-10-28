"""Portable command-line entry point; serving defaults to this workspace only."""

import argparse
import ipaddress
import os
from pathlib import Path

from .paths import RuntimePaths
from .version import __version__


def _loopback_host(value: str) -> str:
    if value == 'localhost':
        return value
    try:
        if ipaddress.ip_address(value).is_loopback:
            return value
    except ValueError:
        pass
    raise argparse.ArgumentTypeError('仅允许 loopback 地址，例如 127.0.0.1、localhost 或 ::1。')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='zhixu', description='知序：本机资料检索与有出处的问答。')
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    commands = parser.add_subparsers(dest='command')
    serve = commands.add_parser('serve', help='启动本机知识库网页服务。')
    serve.add_argument('--host', type=_loopback_host, default='127.0.0.1')
    serve.add_argument('--port', type=int, default=18765)
    serve.add_argument('--data-dir', type=Path, help='资料库目录；默认使用当前工作目录下的 data。')
    serve.add_argument('--model-dir', type=Path, help='可选本地模型目录。')
    serve.add_argument('--demo', action='store_true', help='在新资料库中导入明确标识的模拟资料。')
    serve.add_argument('--no-browser', action='store_true', help='兼容选项；CLI 默认不打开浏览器。')
    serve.add_argument('--enterprise', action='store_true', default=None, help='启用账号、角色与空间权限；须先初始化管理员。')
    admin = commands.add_parser('admin', help='在本机初始化企业管理员。')
    admin_commands = admin.add_subparsers(dest='admin_command', required=True)
    initialize = admin_commands.add_parser('init', help='首次创建管理员与默认知识空间，无默认密码。')
    initialize.add_argument('--data-dir', type=Path)
    initialize.add_argument('--username', required=True)
    reset_password = admin_commands.add_parser('reset-password', help='本机维护者重置密码并吊销该账号所有会话。')
    reset_password.add_argument('--data-dir', type=Path)
    reset_password.add_argument('--username', required=True)
    backup = commands.add_parser('backup', help='创建校验备份或恢复到新的空目录。')
    backup_commands = backup.add_subparsers(dest='backup_command', required=True)
    create = backup_commands.add_parser('create')
    create.add_argument('--data-dir', type=Path)
    create.add_argument('--output', type=Path, required=True)
    restore = backup_commands.add_parser('restore')
    restore.add_argument('--archive', type=Path, required=True)
    restore.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == 'admin':
        import getpass
        from .identity import IdentityError, IdentityStore
        password = getpass.getpass('管理员密码（至少12字符）：')
        confirmation = getpass.getpass('再次输入密码：')
        if password != confirmation:
            print('两次密码不一致，未创建账号。')
            return 1
        paths = RuntimePaths.discover(data_dir=args.data_dir)
        try:
            identity = IdentityStore(paths.data_dir / 'control.db')
            if args.admin_command == 'init':
                user = identity.bootstrap(args.username, password)
                workspace = identity.create_workspace('团队知识库')
                identity.audit(user['id'], 'system.bootstrap', workspace_id=workspace['id'])
            else:
                user = next((item for item in identity.list_users() if item['username'] == args.username.casefold()), None)
                if user is None:
                    raise IdentityError('账号不存在。')
                identity.reset_password(user['id'], password)
                identity.audit(user['id'], 'user.password_reset')
        except (IdentityError, OSError) as error:
            print(str(error) if isinstance(error, IdentityError) else '初始化失败，请检查数据目录权限。')
            return 1
        print('管理员和团队知识库已初始化。使用 zhixu serve --enterprise --data-dir PATH 启动。' if args.admin_command == 'init'
              else '密码已重置，该账号所有现有会话已失效。')
        return 0
    if args.command == 'backup':
        from .backup import create_backup, restore_backup
        try:
            if args.backup_command == 'create':
                manifest = create_backup(RuntimePaths.discover(data_dir=args.data_dir).data_dir, args.output)
            else:
                manifest = restore_backup(args.archive, args.destination)
        except (ValueError, OSError):
            print('备份或恢复失败。请检查归档、校验值、源目录与目标目录；不会覆盖现有资料。')
            return 1
        print(f"校验完成：{len(manifest['files'])} 个文件，逐数据库一致。备份包含敏感资料与配置，请受控存储。")
        return 0
    if not 1 <= args.port <= 65535:
        parser.error('--port 须在 1 到 65535 之间。')
    paths = RuntimePaths.discover(data_dir=args.data_dir, model_dir=args.model_dir)
    os.environ['ZHIXU_DATA_DIR'] = str(paths.data_dir)
    os.environ['ZHIXU_MODEL_DIR'] = str(paths.model_dir)
    os.environ['ZHIXU_SEED_DEMO'] = '1' if args.demo else '0'
    os.environ['ZHIXU_HOST'] = args.host
    os.environ['ZHIXU_PORT'] = str(args.port)
    if args.enterprise is not None:
        os.environ['ZHIXU_ENTERPRISE'] = '1' if args.enterprise else '0'
    import uvicorn
    uvicorn.run('app.main:create_app', factory=True, host=args.host, port=args.port, log_level='info')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

import paramiko
import sys

def test_connection(hostname, username, password):
    try:
        # 创建 SSH 客户端
        client = paramiko.SSHClient()
        # 自动添加策略，保存服务器的 SSH 密钥
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # 连接服务器
        print(f"正在尝试连接 {hostname}...")
        client.connect(hostname=hostname, username=username, password=password, timeout=10)
        print("连接成功！")
        
        # 执行一些基础命令检查环境
        commands = [
            "uname -a",
            "psql --version || echo 'PostgreSQL not found'",
            "docker --version || echo 'Docker not found'",
            "lsb_release -a || cat /etc/os-release"
        ]
        
        for cmd in commands:
            print(f"\n执行命令: {cmd}")
            stdin, stdout, stderr = client.exec_command(cmd)
            out = stdout.read().decode().strip()
            err = stderr.read().decode().strip()
            if out: print(f"输出: {out}")
            if err: print(f"错误: {err}")
            
        client.close()
    except Exception as e:
        print(f"连接失败: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    test_connection("8.138.101.86", "root", "!yyf19981122")

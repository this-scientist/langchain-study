import paramiko
import sys

def check_postgres(hostname, username, password):
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(hostname=hostname, username=username, password=password, timeout=10)
        
        # 检查正在运行的服务
        print("检查 PostgreSQL 服务状态...")
        stdin, stdout, stderr = client.exec_command("systemctl status postgresql || systemctl status postgresql-13")
        print(stdout.read().decode())
        
        # 列出数据库
        print("列出当前数据库...")
        # 尝试使用 sudo -u postgres psql -l，如果不行则直接 psql -l
        stdin, stdout, stderr = client.exec_command("sudo -u postgres psql -l")
        print(stdout.read().decode())
        
        client.close()
    except Exception as e:
        print(f"操作失败: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    check_postgres("8.138.101.86", "root", "!yyf19981122")

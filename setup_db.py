import paramiko
import os

def setup_database(hostname, username, password, local_schema_path):
    try:
        # 1. 连接 SSH
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(hostname=hostname, username=username, password=password, timeout=10)
        
        # 2. 上传 schema.sql
        print(f"正在上传 {local_schema_path}...")
        sftp = client.open_sftp()
        remote_path = "/tmp/schema.sql"
        sftp.put(local_schema_path, remote_path)
        sftp.close()
        
        # 3. 创建数据库 (如果不存在)
        db_name = "langchain_db"
        print(f"正在检查/创建数据库 {db_name}...")
        create_db_cmd = f"sudo -u postgres psql -tc \"SELECT 1 FROM pg_database WHERE datname = '{db_name}'\" | grep -q 1 || sudo -u postgres psql -c \"CREATE DATABASE {db_name}\""
        client.exec_command(create_db_cmd)
        
        # 4. 执行 schema.sql
        print(f"正在执行数据库初始化脚本...")
        exec_schema_cmd = f"sudo -u postgres psql -d {db_name} -f {remote_path}"
        stdin, stdout, stderr = client.exec_command(exec_schema_cmd)
        
        out = stdout.read().decode()
        err = stderr.read().decode()
        
        if out: print(f"标准输出:\n{out}")
        if err: print(f"标准错误:\n{err}")
        
        # 5. 验证表是否创建成功
        print("\n验证创建的表:")
        stdin, stdout, stderr = client.exec_command(f"sudo -u postgres psql -d {db_name} -c \"\\dt\"")
        print(stdout.read().decode())
        
        client.close()
        print("数据库初始化完成！")
        
    except Exception as e:
        print(f"操作失败: {str(e)}")

if __name__ == "__main__":
    setup_database("8.138.101.86", "root", "!yyf19981122", "sql/schema.sql")

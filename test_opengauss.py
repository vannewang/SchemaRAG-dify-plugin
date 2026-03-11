import os
import sys

# 把当前路径加进去，防止找不到包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import DatabaseConfig, LoggerConfig
from service.database_service import DatabaseService
import json
from datetime import datetime, date

class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)

def test_local_connection():
    # 填入你的 openGauss 数据库信息
    db_type = "postgresql"         # openGauss 用 postgresql 的驱动
    host = "192.168.1.16"
    port = 5136                 # openGauss 的真实端口
    user = "gaussdb"
    password = "Seenton123!"        # 此时可以用之前改好的 MD5 密码
    database = "postgres"
    schema = "aicloud_inspect"   # 指定 openGauss 里的 schema
    
    db_service = DatabaseService()
    
    try:
        query = "select * from aicloud_inspect.alarm limit 10;"
        print(f"开始尝试执行查询: {query}")
        
        # 执行查询
        results, columns = db_service.execute_query(
            db_type=db_type,
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=database,
            query=query
        )
        
        print("\n[SUCCESS] 查询成功！数据预览：")
        print("-" * 50)
        # 美化格式输出前2条数据
        print(f"列名: {columns}")
        print(json.dumps(results[:2], ensure_ascii=False, indent=2, cls=CustomJSONEncoder))
        print("-" * 50)
        
    except Exception as e:
        print(f"\n[FAIL] 查询失败！具体原因是:\n{e}")
    finally:
        db_service.close_all_connections()

if __name__ == "__main__":
    test_local_connection()

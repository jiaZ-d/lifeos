import sqlite3

c = sqlite3.connect(":memory:")
c.execute("CREATE VIRTUAL TABLE t USING fts5(title, content, tokenize='trigram')")
c.execute("INSERT INTO t VALUES ('跑步5公里', '今晚在公园跑了5公里,感觉很好')")
c.execute("INSERT INTO t VALUES ('工作复盘', '完成了季度汇报的PPT初稿')")
r1 = c.execute("SELECT title FROM t WHERE t MATCH '跑了5公里'").fetchall()
r2 = c.execute("SELECT title FROM t WHERE t MATCH '季度汇报'").fetchall()
r3 = c.execute("SELECT title FROM t WHERE t MATCH '跑步'").fetchall()  # 2-char: trigram limitation
print("FTS5 trigram ok:", r1, r2, "| 2-char query:", r3)

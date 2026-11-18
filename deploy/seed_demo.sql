INSERT INTO tenants (name, slug)
VALUES ('示例科技', 'demo-company')
ON CONFLICT (slug) DO NOTHING;

INSERT INTO departments (tenant_id, code, name)
SELECT t.id, d.code, d.name
FROM tenants AS t
CROSS JOIN (
    VALUES
        ('HR', '人力资源部'),
        ('IT', '技术研发部'),
        ('FINANCE', '财务部'),
        ('ADMIN', '行政部')
) AS d(code, name)
WHERE t.slug = 'demo-company'
ON CONFLICT (tenant_id, code) DO NOTHING;

SELECT t.name AS company, d.code, d.name AS department
FROM departments AS d
JOIN tenants AS t ON t.id = d.tenant_id
WHERE t.slug = 'demo-company'
ORDER BY d.code;


INSERT INTO tenants (name, slug)
VALUES ('另一家演示企业', 'other-demo-company')
ON CONFLICT (slug) DO NOTHING;

INSERT INTO knowledge_bases (tenant_id, name)
SELECT id,
       CASE slug
           WHEN 'demo-company' THEN '公司共享知识库'
           ELSE '另一家企业的共享知识库'
       END
FROM tenants
WHERE slug IN ('demo-company', 'other-demo-company')
ON CONFLICT (tenant_id, name) DO NOTHING;

INSERT INTO knowledge_bases (tenant_id, department_id, name)
SELECT d.tenant_id, d.id, d.code || ' 部门知识库'
FROM departments AS d
JOIN tenants AS t ON t.id = d.tenant_id
WHERE t.slug = 'demo-company' AND d.code IN ('IT', 'HR')
ON CONFLICT (tenant_id, name) DO NOTHING;

INSERT INTO documents (id, tenant_id, knowledge_base_id, title)
SELECT seed.id::uuid, kb.tenant_id, kb.id, seed.title
FROM (
    VALUES
        ('d0000000-0000-4000-8000-000000000001',
         'IT 部门知识库', '开发环境配置指南'),
        ('d0000000-0000-4000-8000-000000000002',
         'HR 部门知识库', '员工入职办理流程')
) AS seed(id, kb_name, title)
JOIN knowledge_bases AS kb ON kb.name = seed.kb_name
JOIN tenants AS t ON t.id = kb.tenant_id
WHERE t.slug = 'demo-company'
ON CONFLICT (id) DO NOTHING;

SELECT kb.name AS knowledge_base, kb.id AS kb_id, d.title
FROM documents AS d
JOIN knowledge_bases AS kb ON kb.id = d.knowledge_base_id
WHERE d.id IN (
    'd0000000-0000-4000-8000-000000000001',
    'd0000000-0000-4000-8000-000000000002'
)
ORDER BY kb.name;

#!/usr/bin/env python3
"""Print SQL for a NEW, ISOLATED acceptance database only. Never use on production.
Set GTM_TEST_PASSWORD to a random test-only password; generated SQL contains hashes.
"""
import hashlib
import os
import secrets


def seed(password):
    statements = []
    def add(sql):
        statements.append(sql)
    for role in ['admin', 'reader', 'editor', 'auditor', 'empty']:
        name = 'gtm-' + role
        salt = secrets.token_bytes(32)
        hashed = hashlib.sha256((password + salt.hex().upper()).encode()).hexdigest()
        add("INSERT INTO guacamole_entity (name,type) VALUES ('" + name + "','USER');")
        add("INSERT INTO guacamole_user (entity_id,password_hash,password_salt,password_date) SELECT entity_id,decode('" + hashed + "','hex'),decode('" + salt.hex() + "','hex'),now() FROM guacamole_entity WHERE name='" + name + "';")
    for name in ['Servers', 'Network']:
        add("INSERT INTO guacamole_connection_group (connection_group_name,type) VALUES ('" + name + "','ORGANIZATIONAL');")
    for name, protocol, group in [('Windows Lab','rdp',None), ('Linux Lab','ssh','Servers'), ('Router Lab','ssh','Network'), ('VNC Lab','vnc',None), ('Hidden Lab','ssh',None)]:
        parent = 'NULL' if group is None else "(SELECT connection_group_id FROM guacamole_connection_group WHERE connection_group_name='" + group + "')"
        add("INSERT INTO guacamole_connection (connection_name,protocol,parent_id) VALUES ('" + name + "','" + protocol + "'," + parent + ");")
        for key, value in [('hostname','192.0.2.10'), ('port',{'rdp':'3389','ssh':'22','vnc':'5900'}[protocol]), ('password','TEST_ONLY_DO_NOT_RENDER')]:
            add("INSERT INTO guacamole_connection_parameter (connection_id,parameter_name,parameter_value) SELECT connection_id,'" + key + "','" + value + "' FROM guacamole_connection WHERE connection_name='" + name + "';")
    for role in ['reader', 'editor', 'auditor']:
        add("INSERT INTO guacamole_connection_permission (entity_id,connection_id,permission) SELECT e.entity_id,c.connection_id,'READ' FROM guacamole_entity e CROSS JOIN guacamole_connection c WHERE e.name='gtm-" + role + "' AND c.connection_name != 'Hidden Lab';")
        add("INSERT INTO guacamole_connection_group_permission (entity_id,connection_group_id,permission) SELECT e.entity_id,c.connection_group_id,'READ' FROM guacamole_entity e CROSS JOIN guacamole_connection_group c WHERE e.name='gtm-" + role + "';")
    add("INSERT INTO guacamole_connection_permission (entity_id,connection_id,permission) SELECT e.entity_id,c.connection_id,'UPDATE' FROM guacamole_entity e CROSS JOIN guacamole_connection c WHERE e.name='gtm-editor' AND c.connection_name='Windows Lab';")
    for role, permission in [('admin','ADMINISTER'),('auditor','AUDIT')]:
        add("INSERT INTO guacamole_system_permission (entity_id,permission) SELECT entity_id,'" + permission + "' FROM guacamole_entity WHERE name='gtm-" + role + "';")
    add("INSERT INTO guacamole_connection_history (user_id,username,connection_id,connection_name,start_date,end_date,remote_host) SELECT u.user_id,e.name,c.connection_id,c.connection_name,now()-interval '2 minutes',now()-interval '1 minute','192.0.2.25' FROM guacamole_user u JOIN guacamole_entity e ON e.entity_id=u.entity_id CROSS JOIN guacamole_connection c WHERE e.name='gtm-reader' AND c.connection_name='Windows Lab';")
    return '\n'.join(statements) + '\n'


if __name__ == '__main__':
    password = os.environ['GTM_TEST_PASSWORD']
    print(seed(password), end='')

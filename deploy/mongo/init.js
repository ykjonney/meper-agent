// MongoDB initialization script (runs once on first container start)
// Creates the application database and user

db = db.getSiblingDB('agent_flow');

// Create application user (if not using root credentials)
// db.createUser({
//   user: 'agentflow_app',
//   pwd: 'changeme',
//   roles: [{ role: 'readWrite', db: 'agent_flow' }]
// });

// Placeholder: create initial collections with validation
// Real collections and indexes are created by scripts/init_mongo.py

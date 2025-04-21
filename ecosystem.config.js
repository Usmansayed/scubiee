module.exports = {
  apps: [{
    name: "social-server",
    script: "./index.js",
    instances: 1,             // Set to 1 instance only
    exec_mode: "fork",        // Use fork mode instead of cluster for single instance
    watch: false,
    max_memory_restart: "2G",
    env: {
      NODE_ENV: "production",
    },
    // PM2 specific configurations
    autorestart: true,
    max_restarts: 10,
    restart_delay: 4000,
    
    // Set this to false to ensure no multiple instances
    instance_var: "INSTANCE_ID",
    
    // Graceful shutdown settings
    kill_timeout: 5000,
    listen_timeout: 8000,
    
    // Health monitoring
    exp_backoff_restart_delay: 100,
    
    // Advanced settings
    node_args: "--max-old-space-size=2048", // Adjust memory limit as needed
  }]
};

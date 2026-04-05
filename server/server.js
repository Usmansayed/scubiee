// Add this AFTER your routes but BEFORE starting the server

// Serve static assets
app.use(express.static(path.join(__dirname, '../client/dist')));

// For all other routes, serve the index.html file
app.get('*', (req, res) => {
  res.sendFile(path.resolve(__dirname, '../client/dist', 'index.html'));
});

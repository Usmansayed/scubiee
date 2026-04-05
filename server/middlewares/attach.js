// server/middleware/attachIo.js
module.exports = (io) => (req, res, next) => {
    req.io = io;
    next();
  };
const multer = require('multer');
const path = require('path');
const fs = require('fs');
require('dotenv').config();

// Set storage for local development
const storage = multer.diskStorage({
  destination: (req, file, cb) => {
    const uploadPath = process.env.IMAGE_UPLOAD_DIR || './uploads'; // Fallback if no env set
    if (!fs.existsSync(uploadPath)) {
      fs.mkdirSync(uploadPath, { recursive: true });
    }
    cb(null, uploadPath);
  },
  filename: (req, file, cb) => {
    const uniqueSuffix = Date.now() + '-' + Math.round(Math.random() * 1E9);
    cb(null, file.fieldname + '-' + uniqueSuffix + path.extname(file.originalname));
  }
});

const upload = multer({ storage: storage });

module.exports = upload;

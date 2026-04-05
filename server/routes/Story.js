const express = require('express');
const multer = require('multer');
const ffmpeg = require('fluent-ffmpeg');
const fs = require('fs');
const path = require('path');

const router = express.Router();
const upload = multer({ dest: 'uploads/' });

// Set the path to the ffmpeg binary
ffmpeg.setFfmpegPath('C:/ffmpeg-7.1-essentials_build/ffmpeg-7.1-essentials_build/bin/ffmpeg.exe'); // Update this path to your ffmpeg binary location

router.post('/download', upload.single('file'), (req, res) => {
  const file = req.file;
  const outputPath = path.join(__dirname, '..', 'uploads', `${Date.now()}.mp4`);

  if (file.mimetype === 'video/webm') {
    ffmpeg(file.path)
      .output(outputPath)
      .on('end', () => {
        fs.unlinkSync(file.path); // Remove the original file
        res.json({ url: `http://localhost:5001/uploads/${path.basename(outputPath)}` });
      })
      .on('error', () => {
        res.status(500).send('Error processing video');
      })
      .run();
  } else {
    const imageBuffer = Buffer.from(file.buffer.split(',')[1], 'base64');
    fs.writeFileSync(file.path, imageBuffer);

    ffmpeg(file.path)
      .inputOptions('-loop 1')
      .duration(5) // 5 seconds duration for the image video
      .output(outputPath)
      .on('end', () => {
        fs.unlinkSync(file.path); // Remove the original file
        res.json({ url: `http://localhost:5001/uploads/${path.basename(outputPath)}` });
      })
      .on('error', () => {
        res.status(500).send('Error processing image');
      })
      .run();
  }
});

module.exports = router;
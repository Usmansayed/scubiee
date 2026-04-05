const express = require('express');
const router = express.Router();
const userModel = require('./users');
const postModel = require('./post');
const passport = require('passport');
const localStrategy = require('passport-local');
const upload = require('./multer');
const shortid = require('shortid');
const fs = require('fs');
const path = require('path');

passport.use(new localStrategy(userModel.authenticate()));

// Middleware to check if user is logged in
function isLoggedIn(req, res, next) {
    if (req.isAuthenticated()) {
        return next();
    }
    res.redirect('/login'); // Or handle unauthorized access appropriately
}

// ... existing code ...
// (Assuming routes like '/', '/like', '/unlike', '/comment', '/delete/:id' might already exist here)

// Route to get details of a specific short video
router.get('/short/details/:id', isLoggedIn, async function(req, res, next) {
    try {
        const post = await postModel.findById(req.params.id).populate('user');
        if (!post || !post.isVideo) {
            return res.status(404).send('Short video not found');
        }
        const currentUser = await userModel.findById(req.user._id); // Fetch current user details if needed
        res.render('shortDetails', { post, currentUser, nav: true }); // Assuming 'shortDetails.ejs' exists
    } catch (error) {
        console.error("Error fetching short details:", error);
        next(error);
    }
});

// Route to get posts created by the logged-in user
router.get('/usersposts', isLoggedIn, async function(req, res, next) {
    try {
        const user = await userModel.findById(req.user._id).populate({
            path: 'posts',
            options: { sort: { createdAt: -1 } } // Sort posts by creation date, newest first
        });
        res.render('usersposts', { user, posts: user.posts, nav: true }); // Assuming 'usersposts.ejs' exists
    } catch (error) {
        console.error("Error fetching user posts:", error);
        next(error);
    }
});

// Route to handle creation of a new short video post
router.post('/create-short', isLoggedIn, upload.single('videoFile'), async function(req, res, next) {
    try {
        if (!req.file) {
            return res.status(400).send('No video file uploaded.');
        }

        const user = await userModel.findById(req.user._id);
        if (!user) {
            // Optionally remove the uploaded file if user not found
            fs.unlinkSync(req.file.path);
            return res.status(404).send('User not found.');
        }

        const newPost = await postModel.create({
            user: user._id,
            title: req.body.title || 'Untitled Short', // Use title from form or default
            description: req.body.description || '', // Use description from form or default
            mediaUrl: req.file.filename, // Save the filename from multer
            isVideo: true, // Mark this post as a video
            // Add any other relevant fields like tags, etc. from req.body
        });

        user.posts.push(newPost._id);
        await user.save();

        res.redirect('/profile'); // Redirect to profile or feed after creation

    } catch (error) {
        console.error("Error creating short:", error);
        // Clean up uploaded file in case of error
        if (req.file && req.file.path) {
            try {
                fs.unlinkSync(req.file.path);
            } catch (unlinkError) {
                console.error("Error deleting uploaded file after failed short creation:", unlinkError);
            }
        }
        next(error);
    }
});


// ... rest of the existing code ...

module.exports = router;

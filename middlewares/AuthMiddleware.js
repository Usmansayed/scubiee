const { verify } = require('jsonwebtoken');
require('dotenv').config();

const JWT_SECRET = process.env.JWT_SECRET;

const validateToken = (req, res, next) => {
    const accessToken = req.cookies.access_token; // Read the token from the cookies

    if (!accessToken) {
        return res.status(401).json({ error: "User not logged in" });
    }

    try {
        const validToken = verify(accessToken, JWT_SECRET);
        req.user = validToken; // Attach the decoded token data to req.user
        next();  // Proceed to the next middleware or route handler
    } catch (err) {
        return res.status(403).json({ error: "Invalid Token" });
    }
}

module.exports = { validateToken };
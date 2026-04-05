// Updated validateToken middleware to be optional
const optionalValidateToken = (req, res, next) => {
    const accessToken = req.header("accessToken");
  
    if (!accessToken) return next(); // No token, move to next middleware
  
    try {
      const validToken = jwt.verify(accessToken, "importantSecret");
      req.user = validToken;
      return next();
    } catch (err) {
      return next(); // Invalid token, move to next middleware
    }
  };
  
  router.get("/", optionalValidateToken, async (req, res) => {
    const listOfPosts = await Posts.findAll({ include: [Likes] });
    let likedPosts = [];
  
    // If req.user exists, the user is logged in
    if (req.user) {
      const UserId = req.user.id;
      likedPosts = await Likes.findAll({ where: { UserId: UserId } });
    }
  
    res.json({ listOfPosts: listOfPosts, likedPosts: likedPosts });
  });
  
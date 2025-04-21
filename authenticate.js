const passport = require('passport');
const { Users } = require("./models");
const GoogleStrategy = require('passport-google-oauth2').Strategy;
const GitHubStrategy = require('passport-github2').Strategy;




const GOOGLE_CLIENT_ID = process.env.GOOGLE_CLIENT_ID ;
const GOOGLE_CLIENT_SECRET = process.env.GOOGLE_CLIENT_SECRET ;

const api = process.env.VITE_API_URL ;


passport.use(new GoogleStrategy({
  clientID: GOOGLE_CLIENT_ID,
  clientSecret: GOOGLE_CLIENT_SECRET,
  callbackURL: `${api}/user/google/callback`,
  passReqToCallback: true
},
async function(request, accessToken, refreshToken, profile, done) {
  try {
    // Extract email properly from Google profile
    const email = profile.emails && profile.emails.length > 0 
      ? profile.emails[0].value 
      : profile.email; // Fallback for different profile structures
    
    if (!email) {
      console.error('No email provided by Google OAuth');
      return done(null, false);
    }
    
    
    // Check if user already exists in the database
    const existingUser = await Users.findOne({ where: { email } });
    
    if (existingUser) {
      // For existing users, set them directly in the request object
      // so we can generate token in the callback
      request.existingUser = existingUser;
    } else {
      // For new users, set temporary data
      const userData = {
        sub: profile.id,
        email,
        given_name: profile.name?.givenName || profile.given_name,
        family_name: profile.name?.familyName || profile.family_name
      };
      
      if (!request.session) {
        request.session = {};
      }
      request.session.tempUserData = userData;
      
      // Also set cookie as backup
      request.res.cookie('temp_user_data', JSON.stringify(userData), {
        httpOnly: true,
        secure: false,
        maxAge: 3600000 // 1 hour
      });
    }
    
    return done(null, profile);
  } catch (error) {
    console.error('Error in Google OAuth strategy:', error);
    return done(error, false);
  }
}));



    passport.serializeUser((user, done) => {
      done(null, user.id);
    });

    passport.deserializeUser((id, done) => {
      Users.findByPk(id)
        .then(user => done(null, user))
        .catch(done);
    });

module.exports = passport;
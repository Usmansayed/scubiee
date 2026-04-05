const express = require("express");
const router = express.Router();
const { validateToken } = require("../middlewares/AuthMiddleware");
const { Queries, Users } = require("../models");
const sequelize = require("../models").sequelize;

// Submit a support query/request
router.post("/submit-query", validateToken, async (req, res) => {
  try {
    // First, validate the Queries table exists
    try {
      await Queries.findOne(); // This will throw an error if table doesn't exist
    } catch (tableError) {
      console.error("Queries table check failed:", tableError);
      
      // Try to create the table if it doesn't exist
      try {
        await sequelize.models.Queries.sync();
      } catch (syncError) {
        console.error("Failed to create Queries table:", syncError);
        return res.status(500).json({
          success: false,
          message: "Database error: Support system is currently unavailable"
        });
      }
    }

    const { subject, category, message } = req.body;
    const userId = req.user.id;

    // Validate required fields
    if (!subject || !category || !message) {
      return res.status(400).json({
        success: false,
        message: "Subject, category and message are required"
      });
    }

    // Get user data from the validated token
    const user = await Users.findByPk(userId);
    
    if (!user) {
      return res.status(404).json({
        success: false,
        message: "User not found"
      });
    }

    // Create the support query
    const query = await Queries.create({
      userId: userId,
      name: user.firstName + " " + user.lastName,
      email: user.email,
      subject,
      category,
      message,
      // Status will default to 'pending'
      // Priority will default to 'medium'
    });

    // Return success response with the created query
    return res.status(201).json({
      success: true,
      message: "Your query has been submitted successfully",
      data: {
        id: query.id,
        subject: query.subject,
        status: query.status,
        createdAt: query.createdAt
      }
    });
  } catch (error) {
    console.error("Error submitting support query:", error);
    return res.status(500).json({
      success: false,
      message: "Server error while submitting your query"
    });
  }
});

// Get user's support queries (optional feature)
router.get("/my-queries", validateToken, async (req, res) => {
  try {
    const userId = req.user.id;

    const queries = await Queries.findAll({
      where: { userId },
      order: [['createdAt', 'DESC']],
      attributes: ['id', 'subject', 'category', 'status', 'createdAt']
    });

    return res.status(200).json({
      success: true,
      data: queries
    });
  } catch (error) {
    console.error("Error fetching user queries:", error);
    return res.status(500).json({
      success: false,
      message: "Server error while fetching your queries"
    });
  }
});

module.exports = router;

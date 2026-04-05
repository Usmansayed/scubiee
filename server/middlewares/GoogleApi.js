const path = require('path');

// Set the path to your service account key file
const keyFilePath = path.join(__dirname, '../config/gai-key.json');

// Set the environment variable for Google credentials
process.env.GOOGLE_APPLICATION_CREDENTIALS = keyFilePath;

let ai, model;

// Initialize Google GenAI using dynamic import
async function initializeGoogleAI() {
  if (!ai) {
    try {
      const { GoogleGenAI } = await import('@google/genai');
      
      // Initialize Vertex with your Cloud project and location
      ai = new GoogleGenAI({
        vertexai: true,
        project: 'charming-storm-456918-s6',
        location: 'global'
      });
      model = 'gemini-2.0-flash-001';
      
      console.log('Google GenAI initialized successfully');
    } catch (error) {
      console.error('Failed to initialize Google GenAI:', error);
      throw new Error('Google GenAI initialization failed: ' + error.message);
    }
  }
  return { ai, model };
}

// Set up generation config
const generationConfig = {
  maxOutputTokens: 8192,
  temperature: 1,
  topP: 1,
  safetySettings: [
    {
      category: 'HARM_CATEGORY_HATE_SPEECH',
      threshold: 'OFF',
    },
    {
      category: 'HARM_CATEGORY_DANGEROUS_CONTENT',
      threshold: 'OFF',
    },
    {
      category: 'HARM_CATEGORY_SEXUALLY_EXPLICIT',
      threshold: 'OFF',
    },
    {
      category: 'HARM_CATEGORY_HARASSMENT',
      threshold: 'OFF',
    }
  ],
};

// Function to generate paper metadata from user description
const generatePaperMetadata = async (userDescription) => {
  try {
    // Initialize Google AI if not already done
    const { ai: googleAI, model: modelName } = await initializeGoogleAI();

    // Create the enhanced prompt text with user description
    const promptText = `You are a powerful assistant that converts a user's free-form news feed description into a structured metadata matrix for personalized news recommendations. Do NOT just extract keywords — instead, interpret and expand the intent by inferring missing context, enriching vague prompts, and generating relevant metadata.

Input:
"""
${userDescription}
"""

Your output must follow this structure and logic:

- Add **semantic and contextual meaning**. For example, if the user says "give me football news," expand it with current topics like "player transfers", "match analysis", etc.
- Output **clean, enriched, and deeply inferred** metadata, not just reworded input.
- Return strictly **valid JSON** (no markdown, no comments, no explanations).

Output JSON fields:

- \`summary\`: Cleaned, 2–5 sentence summary of the user's intent.
- \`primary_topics\`: 6–20 broad topics (e.g., politics, technology, sports).
- \`secondary_topics\`: 12–30 contextual or niche subtopics (e.g., player transfers, election funding).
- \`regions\`:
  - \`cities\`: up to 5 relevant cities.
  - \`states\`: up to 5 states or provinces.
  - \`countries\`: up to 5 countries.
  - \`global_scope\`: true if global interest implied.
- \`excluded_topics\`: Up to 5 topics to avoid.
- \`tone\`: Emotional tone of interest (e.g., neutral, critical, optimistic, urgent).
- \`intent_type\`: One of \`"informative"\`, \`"advocacy"\`, \`"analysis"\`, or \`"awareness"\`.
- \`focus_level\`: \`"specific"\` or \`"broad"\`.
- \`language\`: Language of interest. Default to \`"English"\` if unspecified.
- \`audience\`: Target audience type — e.g., \`"general public"\`, \`"students"\`, \`"policy makers"\`, \`"experts"\`.
- \`content_filters\`:
  - \`requires_facts\`: true/false
  - \`requires_opinion\`: true/false
  - \`exclude_clickbait\`: true/false
  - \`exclude_ads\`: true/false
- \`preferred_sources\`: Up to 5 specific, reputable news outlets, or empty array if not specified.

Requirements:
- Use knowledge of current events and trends to supplement vague inputs.
- Keep lists context-rich but relevant (no random fillers).
- Return only strict JSON. No markdown, no fallback explanations.`;

    // Create chat with model and config
    const chat = googleAI.chats.create({
      model: modelName,
      config: generationConfig
    });

    // Send message and get response stream
    const response = await chat.sendMessageStream({
      message: [{ text: promptText }]
    });

    let fullResponse = '';
    for await (const chunk of response) {
      if (chunk.text) {
        fullResponse += chunk.text;
      }
    }

    // Clean the response to remove markdown formatting
    let cleanedResponse = fullResponse.trim();
    
    // Remove markdown code blocks if present
    if (cleanedResponse.startsWith('```json')) {
      cleanedResponse = cleanedResponse.replace(/^```json\s*/, '').replace(/\s*```$/, '');
    } else if (cleanedResponse.startsWith('```')) {
      cleanedResponse = cleanedResponse.replace(/^```\s*/, '').replace(/\s*```$/, '');
    }
    
    // Remove any leading/trailing whitespace again
    cleanedResponse = cleanedResponse.trim();

    // Parse the JSON response
    const metadata = JSON.parse(cleanedResponse);
    return metadata;

  } catch (error) {
    console.error('Error generating paper metadata:', error);
    
    // Check if it's an import error and provide a more specific message
    if (error.message.includes('ERR_REQUIRE_ESM')) {
      throw new Error('Google GenAI module loading failed. Please ensure the @google/genai package is properly installed.');
    }
    
    throw new Error('Failed to generate paper metadata: ' + error.message);
  }
};

// Function to detect post categories from content
const detectPostCategories = async (postContent) => {
  try {
    // Initialize Google AI if not already done
    const { ai: googleAI, model: modelName } = await initializeGoogleAI();

    // Create the prompt text for category detection
    const promptText = `You are a smart classification assistant for a social media platform.

Your job is to read the following post content and choose the 1 to 5 most relevant topics from the predefined list of categories. 

Only choose categories that clearly match the subject matter of the post. If the post fits multiple topics, list all relevant ones, but no more than 5.

Respond ONLY with a valid JSON array of the exact matching categories from the list below. Do NOT explain your choices. Do not add new categories. Do not include any markdown formatting.

Categories:
[
 "Politics", "Technology", "Sports", "Social Media", "Business", 
 "Science", "Health", "Entertainment", "World News", "Local News", 
 "Environment", "Education", "Crime", "Law & Justice", "Culture", 
 "Travel", "Food & Cuisines", "Fashion", "Lifestyle", "Automobile", 
 "Space & Astronomy", "History", "Finance", "Real Estate", "Social Issues", 
 "Startups & Entrepreneurship", "Gaming", "Military & Defense", 
 "Religion & Spirituality"
]

Post Content:
"""
${postContent}
"""

Respond with:
["Category1", "Category2", ..., "CategoryN"]`;

    // Create chat with model and config
    const categoryGenerationConfig = {
      maxOutputTokens: 217,
      temperature: 0.3, // Lower temperature for more consistent categorization
      topP: 1,
      safetySettings: [
        {
          category: 'HARM_CATEGORY_HATE_SPEECH',
          threshold: 'OFF',
        },
        {
          category: 'HARM_CATEGORY_DANGEROUS_CONTENT',
          threshold: 'OFF',
        },
        {
          category: 'HARM_CATEGORY_SEXUALLY_EXPLICIT',
          threshold: 'OFF',
        },
        {
          category: 'HARM_CATEGORY_HARASSMENT',
          threshold: 'OFF',
        }
      ],
    };

    const chat = googleAI.chats.create({
      model: modelName,
      config: categoryGenerationConfig
    });

    // Send message and get response stream
    const response = await chat.sendMessageStream({
      message: [{ text: promptText }]
    });

    let fullResponse = '';
    for await (const chunk of response) {
      if (chunk.text) {
        fullResponse += chunk.text;
      }
    }

    // Clean the response to remove any markdown formatting
    let cleanedResponse = fullResponse.trim();
    
    // Remove markdown code blocks if present
    if (cleanedResponse.startsWith('```json')) {
      cleanedResponse = cleanedResponse.replace(/^```json\s*/, '').replace(/\s*```$/, '');
    } else if (cleanedResponse.startsWith('```')) {
      cleanedResponse = cleanedResponse.replace(/^```\s*/, '').replace(/\s*```$/, '');
    }
    
    // Remove any leading/trailing whitespace again
    cleanedResponse = cleanedResponse.trim();

    // Parse the JSON response
    const categories = JSON.parse(cleanedResponse);
    
    // Validate that it's an array and contains valid categories
    if (!Array.isArray(categories)) {
      throw new Error('AI response is not an array');
    }
    
    // Fallback to General if no categories detected or invalid response
    if (categories.length === 0) {
      return ["General"];
    }
    
    // Limit to maximum 5 categories as specified
    return categories.slice(0, 5);

  } catch (error) {
    console.error('Error detecting post categories:', error);
    
    // Check if it's an import error and provide a more specific message
    if (error.message.includes('ERR_REQUIRE_ESM')) {
      throw new Error('Google GenAI module loading failed. Please ensure the @google/genai package is properly installed.');
    }
    
    // Return default category on error
    console.warn('Falling back to default category due to error:', error.message);
    return ["General"];
  }
};

module.exports = {
  generatePaperMetadata,
  processDescription: generatePaperMetadata, // Add alias for backwards compatibility
  detectPostCategories
};
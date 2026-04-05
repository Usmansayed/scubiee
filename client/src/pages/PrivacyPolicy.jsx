import React from 'react';

const PrivacyPolicy = () => {
  return (
    <div className="min-h-screen font-sans text-[17px] text-gray-300 max-w-3xl mx-auto px-4 md:px-6 py-8">
      <div className="space-y-6">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold mb-2">Scubiee - Privacy Policy</h1>
          <p className="text-gray-400">Effective Date: March 15, 2024 | Last Updated: March 15, 2024</p>
        </div>

        <div className="mb-8">
          <p className="text-lg">
            Welcome to Scubiee. We respect your privacy and are committed to protecting your personal information. 
            This Privacy Policy explains how we collect, use, disclose, and safeguard your information when you use our platform.
          </p>
          <div className="mt-4 p-3 bg-yellow-900/20 border border-yellow-700/30 rounded-lg">
            <p className="text-yellow-300 font-medium">
              <span className="font-bold">⚠️ BETA VERSION NOTICE:</span> Scubiee is currently in beta testing. As we continue to improve our platform, 
              aspects of this Privacy Policy may change. We will notify users of any material changes.
            </p>
          </div>
        </div>

        {/* Section 1: Information We Collect */}
        <section className="space-y-3">
          <h2 className="text-2xl font-semibold text-white border-b border-gray-700 pb-2">1. Information We Collect</h2>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2">1.1 User-Provided Information</h3>
            <ul className="list-disc pl-5 space-y-2">
              <li><span className="font-medium">Account Information:</span> When you register, we collect your name, email address, username, password, date of birth, and optional profile information.</li>
              <li><span className="font-medium">Profile Information:</span> Profile pictures, cover images, biography, and other details you choose to provide.</li>
              <li><span className="font-medium">Identity Verification:</span> We may collect additional information to verify your identity when required for security purposes or certain platform features.</li>
              <li><span className="font-medium">Social Media Information:</span> If you connect your Scubiee account to social media platforms, we may access information from those accounts (such as your friends or contacts).</li>
              <li><span className="font-medium">Interests and Preferences:</span> Information about your interests, preferences, and account settings.</li>
            </ul>
          </div>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2">1.2 Content Data</h3>
            <ul className="list-disc pl-5 space-y-2">
              <li><span className="font-medium">User-Generated Content:</span> Posts, comments, images, videos, messages, and any other content you create, share, or upload to Scubiee.</li>
              <li><span className="font-medium">Interaction Data:</span> Likes, saves, follows, shares, reports, and other interactions with content or users.</li>
              <li><span className="font-medium">Communication Data:</span> Messages, chats, and other communications between users, including metadata about these communications.</li>
              <li><span className="font-medium">Reports and Feedback:</span> Information you provide when reporting content, submitting feedback, or contacting support.</li>
            </ul>
          </div>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2">1.3 Automatically Collected Information</h3>
            <ul className="list-disc pl-5 space-y-2">
              <li><span className="font-medium">Device Information:</span> Hardware model, operating system, unique device identifiers, mobile network information.</li>
              <li><span className="font-medium">Log Data:</span> IP address, browser type, pages viewed, time spent, timestamps, referral URLs, and other statistics.</li>
              <li><span className="font-medium">Location Data:</span> General location information derived from IP addresses. Precise location is only collected with your explicit permission.</li>
              <li><span className="font-medium">Usage Information:</span> How you use the platform, features you access, actions you take, and time spent on various activities.</li>
              <li><span className="font-medium">Connection Information:</span> Mobile carrier, ISP, and performance data related to our services.</li>
            </ul>
          </div>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2">1.4 Cookies and Similar Technologies</h3>
            <p>
              We use cookies, web beacons, pixels, local storage, and similar technologies to collect information and provide our services. These technologies help us understand how you interact with our platform, remember your preferences, and improve your experience.
            </p>
            <p className="mt-2">
              Types of cookies we use:
            </p>
            <ul className="list-disc pl-5 space-y-2 mt-1">
              <li><span className="font-medium">Essential Cookies:</span> Required for the platform to function properly, including authentication and security.</li>
              <li><span className="font-medium">Preference Cookies:</span> Remember your settings and preferences.</li>
              <li><span className="font-medium">Analytics Cookies:</span> Help us understand how users interact with our platform to improve its functionality.</li>
              <li><span className="font-medium">Third-party Cookies:</span> Set by third-party services we use for analytics, advertising, and functionality.</li>
            </ul>
          </div>
        </section>

        {/* Section 2: How We Use Your Information */}
        <section className="space-y-3">
          <h2 className="text-2xl font-semibold text-white border-b border-gray-700 pb-2">2. How We Use Your Information</h2>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2">2.1 Provide and Maintain Our Services</h3>
            <ul className="list-disc pl-5 space-y-2">
              <li>Create and manage your account.</li>
              <li>Provide the core features and functionality of Scubiee.</li>
              <li>Process transactions and maintain records.</li>
              <li>Fulfill your requests and respond to your inquiries.</li>
              <li>Send service-related notifications and updates.</li>
              <li>Provide customer support and respond to your requests.</li>
            </ul>
          </div>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2">2.2 Personalization and Improvement</h3>
            <ul className="list-disc pl-5 space-y-2">
              <li>Personalize content and recommendations based on your interests and activities.</li>
              <li>Analyze usage patterns to improve platform design and functionality.</li>
              <li>Develop new features, products, and services.</li>
              <li>Measure the effectiveness of our services and features.</li>
              <li>Conduct surveys and research to understand user preferences.</li>
            </ul>
          </div>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2">2.3 Safety, Security, and Integrity</h3>
            <ul className="list-disc pl-5 space-y-2">
              <li>Verify user identity and prevent fraud or unauthorized access.</li>
              <li>Monitor and prevent prohibited or illegal activities.</li>
              <li>Investigate and address violations of our Terms of Service.</li>
              <li>Moderate content and enforce community guidelines.</li>
              <li>Process and investigate reports of abuse or harmful content.</li>
              <li>Protect the rights, property, or safety of Scubiee, our users, or others.</li>
            </ul>
          </div>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2">2.4 Communications</h3>
            <ul className="list-disc pl-5 space-y-2">
              <li>Send administrative messages and communications about your account.</li>
              <li>Notify you about activity related to your account or content.</li>
              <li>Provide information about platform updates, features, or policy changes.</li>
              <li>Respond to your inquiries and support requests.</li>
            </ul>
          </div>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2">2.5 Legal Obligations</h3>
            <ul className="list-disc pl-5 space-y-2">
              <li>Comply with applicable laws, regulations, legal processes, or enforceable governmental requests.</li>
              <li>Enforce our Terms of Service and other policies.</li>
              <li>Protect against legal liability.</li>
              <li>Establish, exercise, or defend legal claims.</li>
            </ul>
          </div>
        </section>

        {/* Section 3: Information Sharing and Disclosure */}
        <section className="space-y-3">
          <h2 className="text-2xl font-semibold text-white border-b border-gray-700 pb-2">3. Information Sharing and Disclosure</h2>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2">3.1 Your Choices About Sharing</h3>
            <p>
              Scubiee is designed as a social platform, and the information you provide may be visible to other users depending on your privacy settings. You can control the visibility of your profile information and content through the privacy settings in your account.
            </p>
            
            <p className="mt-2 italic">
              Note: Information you make publicly available can be viewed, collected, and used by others. Exercise caution when sharing personal information.
            </p>
          </div>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2">3.2 Sharing with Third Parties</h3>
            <p className="mb-2">We may share your information with the following categories of third parties:</p>
            <ul className="list-disc pl-5 space-y-2">
              <li><span className="font-medium">Service Providers:</span> Companies that help us deliver our services, such as hosting providers, cloud storage services, payment processors, customer support tools, and analytics providers.</li>
              <li><span className="font-medium">Business Partners:</span> Companies we partner with for joint marketing efforts, co-branded services, or events.</li>
              <li><span className="font-medium">Affiliated Companies:</span> Companies within the Scubiee family of companies that help provide, understand, and improve our services.</li>
              <li><span className="font-medium">Legal Authorities:</span> Law enforcement, governmental agencies, or authorized third parties, when required by law or in response to valid legal requests.</li>
              <li><span className="font-medium">New Owners:</span> In connection with a merger, acquisition, reorganization, or sale of all or substantially all of our assets.</li>
            </ul>
          </div>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">3.3 No Sale of Personal Information</h3>
            <p>
              <span className="font-bold">We do not sell your personal information to third parties for monetary compensation.</span> We may share information with third parties as described in this Privacy Policy to provide and improve our services.
            </p>
          </div>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">3.4 Aggregated and De-identified Data</h3>
            <p>
              We may share aggregated or de-identified information that cannot reasonably be used to identify you with third parties for industry analysis, research, demographic profiling, and other similar purposes.
            </p>
          </div>
        </section>

        {/* Section 4: Data Security */}
        <section className="space-y-3">
          <h2 className="text-2xl font-semibold text-white border-b border-gray-700 pb-2">4. Data Security</h2>
          
          <div className="pl-4">
            <p>
              We implement reasonable security measures designed to protect your information from unauthorized access, disclosure, alteration, and destruction. These measures include:
            </p>
            <ul className="list-disc pl-5 space-y-2 mt-2">
              <li>Encryption of sensitive information</li>
              <li>Secure server infrastructure</li>
              <li>Regular security assessments</li>
              <li>Access controls for our employees</li>
              <li>Incident response procedures</li>
            </ul>
            <p className="mt-3">
              However, no method of transmission over the internet or electronic storage is 100% secure. While we strive to use commercially acceptable means to protect your information, we cannot guarantee its absolute security.
            </p>
            <p className="mt-3">
              <span className="font-bold">Important Note for Beta Users:</span> As Scubiee is currently in beta, we are continuously improving our security measures. Beta users should be aware that there may be a higher risk of bugs or vulnerabilities during this phase.
            </p>
          </div>
        </section>

        {/* Section 5: Your Rights and Choices */}
        <section className="space-y-3">
          <h2 className="text-2xl font-semibold text-white border-b border-gray-700 pb-2">5. Your Rights and Choices</h2>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2">5.1 Account Information</h3>
            <p>
              You can access, update, or correct most of your account information by logging into your Scubiee account and modifying your profile or account settings. If you need assistance with information that cannot be changed through your account, please contact us.
            </p>
          </div>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">5.2 Content Management</h3>
            <p>
              You can delete most content you share on Scubiee, including posts, comments, and messages. However, please note that:
            </p>
            <ul className="list-disc pl-5 space-y-2 mt-1">
              <li>Some content may persist in backup copies for a reasonable period.</li>
              <li>Content that others have shared about you is not part of your account and will not be deleted when you delete your account.</li>
              <li>Some types of interactions (such as likes, shares, or comments on others' content) may remain visible even after you remove your account.</li>
            </ul>
          </div>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">5.3 Account Deactivation and Deletion</h3>
            <p>
              You can temporarily deactivate your account or permanently delete it:
            </p>
            <ul className="list-disc pl-5 space-y-2 mt-1">
              <li><span className="font-medium">Deactivation:</span> Temporarily hides your profile and content from other users but preserves your information.</li>
              <li><span className="font-medium">Deletion:</span> Permanently removes your account and most personal information associated with it after a brief delay period.</li>
            </ul>
            <p className="mt-2">
              Please note that some information may be retained for legal, security, or business purposes even after account deletion.
            </p>
          </div>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">5.4 Communications Preferences</h3>
            <p>
              You can control the types of notifications and communications you receive from Scubiee through your account settings. Even if you opt out of promotional communications, we may still send you administrative messages regarding your account or our services.
            </p>
          </div>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">5.5 Data Portability</h3>
            <p>
              You can request a copy of certain information that you have provided to us in a structured, commonly used, and machine-readable format.
            </p>
          </div>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">5.6 Exercising Your Rights</h3>
            <p>
              To exercise your rights regarding your personal information, please contact us at privacy@scubiee.com. We will respond to your request within a reasonable timeframe in accordance with applicable laws.
            </p>
          </div>
        </section>

        {/* Section 6: Children's Privacy */}
        <section className="space-y-3">
          <h2 className="text-2xl font-semibold text-white border-b border-gray-700 pb-2">6. Children's Privacy</h2>
          
          <div className="pl-4">
            <p>
              Scubiee is not intended for children under the age of 13 (or the minimum age required in your country). We do not knowingly collect personal information from children under these ages. If we become aware that we have collected personal information from a child under the applicable age without parental consent, we will take steps to delete that information.
            </p>
            <p className="mt-3">
              If you believe we might have any information from or about a child under the applicable age, please contact us immediately at privacy@scubiee.com.
            </p>
          </div>
        </section>

        {/* Section 7: Data Retention */}
        <section className="space-y-3">
          <h2 className="text-2xl font-semibold text-white border-b border-gray-700 pb-2">7. Data Retention</h2>
          
          <div className="pl-4">
            <p>
              We retain your information as long as your account is active or as needed to provide you services. We may also retain and use your information as necessary to:
            </p>
            <ul className="list-disc pl-5 space-y-2 mt-2">
              <li>Comply with our legal obligations</li>
              <li>Resolve disputes</li>
              <li>Enforce our agreements</li>
              <li>Protect our legal interests</li>
              <li>Prevent fraud</li>
              <li>Address technical issues</li>
            </ul>
            <p className="mt-3">
              When we no longer need your information for the purposes outlined in this Privacy Policy, we will delete or anonymize it, unless we have a legitimate business purpose for retaining it or are required by law to retain it for a longer period.
            </p>
          </div>
        </section>

        {/* Section 8: International Data Transfers */}
        <section className="space-y-3">
          <h2 className="text-2xl font-semibold text-white border-b border-gray-700 pb-2">8. International Data Transfers</h2>
          
          <div className="pl-4">
            <p>
              Scubiee is a global platform. Your information may be transferred to, stored, and processed in countries other than the one in which you reside. By using Scubiee, you consent to the transfer of your information to countries which may have different data protection rules than your country.
            </p>
            <p className="mt-3">
              When we transfer personal information from the European Economic Area (EEA), United Kingdom, or Switzerland to countries that have not been deemed to provide an adequate level of protection, we use specific legal mechanisms, such as Standard Contractual Clauses approved by the European Commission, to ensure appropriate safeguards for your information.
            </p>
          </div>
        </section>

        {/* Section 9: Legal Basis for Processing (GDPR) */}
        <section className="space-y-3">
          <h2 className="text-2xl font-semibold text-white border-b border-gray-700 pb-2">9. Legal Basis for Processing (GDPR)</h2>
          
          <div className="pl-4">
            <p>
              For users in the European Economic Area (EEA) and the United Kingdom, we rely on the following legal bases to process your information:
            </p>
            <ul className="list-disc pl-5 space-y-2 mt-2">
              <li><span className="font-medium">Contract:</span> Processing necessary for the performance of our contract with you (i.e., our Terms of Service).</li>
              <li><span className="font-medium">Legitimate Interests:</span> Processing necessary for our legitimate interests, such as developing, improving, and promoting our services and ensuring the security of our platform.</li>
              <li><span className="font-medium">Consent:</span> Processing based on your consent, which you can withdraw at any time.</li>
              <li><span className="font-medium">Legal Obligation:</span> Processing necessary to comply with our legal obligations.</li>
            </ul>
          </div>
        </section>

        {/* Section 10: Legal Disclaimers and Platform Protection */}
        <section className="space-y-3">
          <h2 className="text-2xl font-semibold text-white border-b border-gray-700 pb-2">10. Legal Disclaimers and Platform Protection</h2>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2">10.1 User Content Responsibility</h3>
            <p>
              Scubiee is a platform for user-generated content. Users are solely responsible for the content they post, including its legality, reliability, and appropriateness. We do not endorse or guarantee the accuracy, quality, or legality of any user-generated content.
            </p>
          </div>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">10.2 Beta Status Disclaimer</h3>
            <p>
              As Scubiee is currently in beta, our services are provided on an "as is" and "as available" basis. While we strive to provide a secure and reliable platform, beta services may contain bugs, errors, or other limitations. We make no warranties of any kind regarding the platform during this beta period.
            </p>
          </div>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">10.3 Limitation of Liability</h3>
            <p>
              To the maximum extent permitted by law, Scubiee shall not be liable for:
            </p>
            <ul className="list-disc pl-5 space-y-2 mt-1">
              <li>Any indirect, incidental, special, consequential, or punitive damages.</li>
              <li>Loss of profits, data, use, goodwill, or other intangible losses.</li>
              <li>Unauthorized access to or use of our servers and any personal information stored therein.</li>
              <li>Interruption or cessation of transmission to or from our services.</li>
              <li>Bugs, viruses, or other harmful code transmitted to or through our service by any third party.</li>
              <li>Errors, inaccuracies, or omissions in any content or loss or damage incurred as a result of the use of any content posted, emailed, transmitted, or otherwise made available via the service.</li>
              <li>User-generated content or the defamatory, offensive, or illegal conduct of any third party.</li>
            </ul>
          </div>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">10.4 Indemnification</h3>
            <p>
              You agree to defend, indemnify, and hold harmless Scubiee and its officers, directors, employees, and agents from and against any and all claims, damages, obligations, losses, liabilities, costs, and expenses arising from:
            </p>
            <ul className="list-disc pl-5 space-y-2 mt-1">
              <li>Your use of and access to the platform.</li>
              <li>Your violation of any term of our Terms of Service or this Privacy Policy.</li>
              <li>Your violation of any third-party right, including without limitation any copyright, property, or privacy right.</li>
              <li>Any claim that your content caused damage to a third party.</li>
            </ul>
          </div>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">10.5 Account Termination</h3>
            <p>
              We reserve the right to suspend or terminate accounts that violate our Terms of Service, Community Guidelines, or this Privacy Policy. This includes accounts that:
            </p>
            <ul className="list-disc pl-5 space-y-2 mt-1">
              <li>Post illegal, harmful, or prohibited content.</li>
              <li>Engage in harassment, abuse, or threatening behavior.</li>
              <li>Attempt to impersonate others or create fraudulent accounts.</li>
              <li>Repeatedly infringe upon intellectual property rights.</li>
              <li>Submit false reports or claims against other users.</li>
            </ul>
          </div>
        </section>

        {/* Section 11: Changes to This Privacy Policy */}
        <section className="space-y-3">
          <h2 className="text-2xl font-semibold text-white border-b border-gray-700 pb-2">11. Changes to This Privacy Policy</h2>
          
          <div className="pl-4">
            <p>
              We may update this Privacy Policy from time to time. We will notify you of any changes by posting the new Privacy Policy on this page and, for material changes, we will provide more prominent notice, which may include email notification to the primary email address associated with your account.
            </p>
            <p className="mt-3">
              We encourage you to review this Privacy Policy periodically for any changes. The "Last Updated" date at the top of this page indicates when this Privacy Policy was last revised.
            </p>
            <p className="mt-3">
              Your continued use of Scubiee after changes to this Privacy Policy becomes effective constitutes your acceptance of the revised policy.
            </p>
          </div>
        </section>

        {/* Section 12: Contact Us */}
        <section className="space-y-3">
          <h2 className="text-2xl font-semibold text-white border-b border-gray-700 pb-2">12. Contact Us</h2>
          
          <div className="pl-4">
            <p>
              If you have any questions about this Privacy Policy or our data practices, please contact us at:
            </p>
            <div className="mt-3">
              <p><span className="font-medium">Email:</span> scubiee.inc@gmail.com</p>
              <p><span className="font-medium">Address:</span> Belagavi, Karnataka</p>
            </div>
            <p className="mt-3">
              Please allow up to 7 days for us to respond to your request or inquiry.
            </p>
          </div>
        </section>
      </div>
    </div>
  );
};

export default PrivacyPolicy;

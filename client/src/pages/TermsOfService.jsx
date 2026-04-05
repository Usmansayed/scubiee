import React from 'react';

const TermsOfService = () => {
  return (
    <div className="min-h-screen text-[17px] font-sans text-gray-300 max-w-3xl mx-auto px-4 md:px-6 py-8">
      <div className="space-y-6">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold mb-2">Scubiee - Terms of Service</h1>
          <p className="text-gray-400">Effective Date: March 15, 2024 | Last Updated: March 15, 2024</p>
        </div>

        <div className="mb-8">
          <p className="text-lg">
            Welcome to Scubiee. These Terms of Service govern your use of our website, applications, features, and services. By accessing or using Scubiee, you agree to be bound by these terms.
          </p>
          <div className="mt-4 p-3 bg-yellow-900/20 border border-yellow-700/30 rounded-lg">
            <p className="text-yellow-300 font-medium">
              <span className="font-bold">⚠️ BETA VERSION NOTICE:</span> Scubiee is currently in beta testing. Features, functionality, and performance may change without prior notice. Users accept the platform "as-is" during this phase.
            </p>
          </div>
        </div>

        {/* Section 1: Definitions */}
        <section className="space-y-3">
          <h2 className="text-2xl font-semibold text-white border-b border-gray-700 pb-2">1. Definitions</h2>
          
          <div className="pl-4">
            <ul className="list-disc pl-5 space-y-2">
              <li><span className="font-medium">"Scubiee"</span>, "we", "our", or "us" refers to the Scubiee platform, its owners, operators, and affiliates.</li>
              <li><span className="font-medium">"Service"</span> refers to the Scubiee platform, website, applications, and all related services.</li>
              <li><span className="font-medium">"User"</span>, "you", or "your" refers to any individual or entity using our Service.</li>
              <li><span className="font-medium">"Content"</span> refers to any text, images, videos, comments, messages, or other materials uploaded, shared, or displayed on the Service.</li>
              <li><span className="font-medium">"Beta Version"</span> refers to the current developmental stage of our Service, which is still undergoing testing and refinement.</li>
            </ul>
          </div>
        </section>

        {/* Section 2: Beta Disclaimer */}
        <section className="space-y-3">
          <h2 className="text-2xl font-semibold text-white border-b border-gray-700 pb-2">2. Beta Disclaimer</h2>
          
          <div className="pl-4">
            <p className="mb-3">
              Scubiee is currently in its beta phase, which means:
            </p>
            <ul className="list-disc pl-5 space-y-2">
              <li>The Service may contain bugs, errors, or inaccuracies.</li>
              <li>Features, functionality, and performance may change without prior notice.</li>
              <li>The Service may experience downtime, disruptions, or complete changes to its operation.</li>
              <li>We make no warranties about reliability, availability, or fitness for a particular purpose during this beta phase.</li>
              <li>We may limit, suspend, or terminate any aspect of the Service at our sole discretion during the beta phase.</li>
              <li>User data may not be preserved or may be lost during updates or transitions from beta to full release.</li>
              <li>You understand and accept that you are using a developmental product that is not yet finalized.</li>
            </ul>
            <p className="mt-3 italic">
              By using Scubiee during its beta phase, you acknowledge these limitations and agree to use the Service "as-is" with no expectation of completeness, permanence, or guaranteed performance.
            </p>
          </div>
        </section>

        {/* Section 3: Content Responsibility */}
        <section className="space-y-3">
          <h2 className="text-2xl font-semibold text-white border-b border-gray-700 pb-2">3. Content Responsibility</h2>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2">3.1 User-Generated Content</h3>
            <p className="mb-3">
              Scubiee is a platform that enables users to share and access content created by other users. We do not create, edit, or endorse content shared by users. Each user is solely responsible for the content they publish, including its accuracy, legality, and appropriateness.
            </p>
            
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">3.2 No Verification Obligation</h3>
            <p className="mb-3">
              Scubiee does not and is under no obligation to:
            </p>
            <ul className="list-disc pl-5 space-y-2">
              <li>Verify the accuracy or truthfulness of user content</li>
              <li>Monitor all content posted to the Service</li>
              <li>Fact-check claims or assertions made by users</li>
              <li>Endorse any opinions or views expressed in user content</li>
              <li>Pre-screen content before it appears on the Service</li>
            </ul>
            
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">3.3 Prohibited Content</h3>
            <p className="mb-3">
              You agree not to post, share, or distribute content that:
            </p>
            <ul className="list-disc pl-5 space-y-2">
              <li>Is unlawful, harmful, threatening, abusive, harassing, defamatory, or invasive of another's privacy</li>
              <li>Constitutes hate speech, incites violence, or promotes discrimination</li>
              <li>Infringes upon any intellectual property rights</li>
              <li>Contains software viruses or any malicious code</li>
              <li>Impersonates any person or entity or falsely states your affiliation with a person or entity</li>
              <li>Intentionally spreads misinformation or disinformation that may cause public harm</li>
              <li>Contains sexually explicit or pornographic material</li>
              <li>Exploits or harms minors</li>
              <li>Promotes illegal activities or substances</li>
              <li>Violates any applicable local, state, national, or international law</li>
            </ul>
            
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">3.4 Reporting Content</h3>
            <p className="mb-3">
              If you encounter content that violates these Terms, please report it through our designated reporting features. We reserve the right, but have no obligation, to:
            </p>
            <ul className="list-disc pl-5 space-y-2">
              <li>Review reported content</li>
              <li>Remove or refuse to display content that we believe violates these Terms</li>
              <li>Take action against users who violate these Terms, including suspension or termination of accounts</li>
            </ul>
            
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">3.5 Disclaimer of Liability for Content</h3>
            <p>
              TO THE MAXIMUM EXTENT PERMITTED BY LAW, SCUBIEE EXPLICITLY DISCLAIMS ALL LIABILITY FOR USER CONTENT. YOU UNDERSTAND THAT BY USING THE SERVICE, YOU MAY BE EXPOSED TO CONTENT THAT IS INACCURATE, OFFENSIVE, INDECENT, OR OTHERWISE OBJECTIONABLE. UNDER NO CIRCUMSTANCES WILL SCUBIEE BE LIABLE FOR ANY CONTENT POSTED BY USERS, INCLUDING ANY ERRORS OR OMISSIONS IN SUCH CONTENT, OR ANY LOSS OR DAMAGE INCURRED AS A RESULT OF THE USE OF ANY CONTENT.
            </p>
          </div>
        </section>

        {/* Section 4: User Eligibility */}
        <section className="space-y-3">
          <h2 className="text-2xl font-semibold text-white border-b border-gray-700 pb-2">4. User Eligibility and Conduct</h2>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2">4.1 Age Requirements</h3>
            <p className="mb-3">
              You must be at least 18 years old to use Scubiee. By using the Service, you represent and warrant that you meet this age requirement. If you are under the age of majority in your jurisdiction, you represent that you have obtained parental or guardian consent to use the Service and agree to these Terms.
            </p>
            
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">4.2 Account Integrity</h3>
            <p className="mb-3">
              When creating an account on Scubiee, you agree to:
            </p>
            <ul className="list-disc pl-5 space-y-2">
              <li>Provide accurate, current, and complete information</li>
              <li>Maintain and promptly update your account information</li>
              <li>Keep your account credentials secure and confidential</li>
              <li>Not share your account with anyone else</li>
              <li>Notify us immediately of any unauthorized use of your account</li>
              <li>Not create multiple accounts unless explicitly permitted</li>
              <li>Not impersonate or misrepresent your identity or affiliation</li>
            </ul>
            
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">4.3 Prohibited Conduct</h3>
            <p className="mb-3">
              You agree not to engage in any of the following activities:
            </p>
            <ul className="list-disc pl-5 space-y-2">
              <li>Using the Service for any unlawful purpose</li>
              <li>Harassing, intimidating, or threatening other users</li>
              <li>Engaging in spamming, phishing, or other deceptive practices</li>
              <li>Attempting to access other users' accounts</li>
              <li>Scraping, data mining, or extracting data from the Service without authorization</li>
              <li>Interfering with or disrupting the integrity or performance of the Service</li>
              <li>Circumventing any technological measures employed to restrict access or use</li>
              <li>Using bots, automated scripts, or other means to access the Service</li>
              <li>Selling, transferring, or licensing your account to any third party</li>
            </ul>
          </div>
        </section>

        {/* Section 5: Accountability for News & Claims */}
        <section className="space-y-3">
          <h2 className="text-2xl font-semibold text-white border-b border-gray-700 pb-2">5. Accountability for News & Claims</h2>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2">5.1 Identity Disclosure</h3>
            <p className="mb-3">
              Users who identify themselves as journalists, news organizations, or content creators must:
            </p>
            <ul className="list-disc pl-5 space-y-2">
              <li>Provide accurate information about their identity or organization</li>
              <li>Disclose any potential conflicts of interest when reporting on stories</li>
              <li>Clearly distinguish between reporting and opinion/commentary</li>
              <li>Not misrepresent their credentials, expertise, or affiliations</li>
            </ul>
            
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">5.2 Source Verification</h3>
            <p className="mb-3">
              When sharing news, information, or claims, users should:
            </p>
            <ul className="list-disc pl-5 space-y-2">
              <li>Use verified and reliable sources when possible</li>
              <li>Provide citations or references for factual claims when appropriate</li>
              <li>Clearly distinguish between verified facts and unverified information</li>
              <li>Update or correct information that is later found to be inaccurate</li>
              <li>Label opinion, commentary, satire, or parody as such</li>
            </ul>
            
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">5.3 Misinformation Policy</h3>
            <p className="mb-3">
              Scubiee takes the spread of misinformation seriously. We may take action against accounts that repeatedly:
            </p>
            <ul className="list-disc pl-5 space-y-2">
              <li>Share demonstrably false information with intent to mislead</li>
              <li>Manipulate content to misrepresent events or statements</li>
              <li>Promote conspiracy theories that have been widely debunked</li>
              <li>Share harmful misinformation related to public health, safety, elections, or civic processes</li>
              <li>Fail to correct significant errors in their posts</li>
            </ul>
            
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">5.4 Enforcement Actions</h3>
            <p className="mb-3">
              For violations of these accountability standards, Scubiee may:
            </p>
            <ul className="list-disc pl-5 space-y-2">
              <li>Add warning labels to content</li>
              <li>Reduce visibility or distribution of content</li>
              <li>Request corrections or clarifications</li>
              <li>Temporarily suspend accounts</li>
              <li>Permanently terminate accounts for severe or repeated violations</li>
              <li>Remove specific content that violates these Terms</li>
            </ul>
            <p className="mt-3 italic">
              Enforcement decisions are made at Scubiee's sole discretion and may depend on various factors, including the severity and frequency of violations, potential for harm, and context.
            </p>
          </div>
        </section>

        {/* Section 6: Intellectual Property */}
        <section className="space-y-3">
          <h2 className="text-2xl font-semibold text-white border-b border-gray-700 pb-2">6. Intellectual Property</h2>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2">6.1 User Content Ownership</h3>
            <p className="mb-3">
              You retain all ownership rights to the content you submit, post, or display on or through the Service. By submitting, posting, or displaying content, you grant Scubiee a worldwide, non-exclusive, royalty-free license (with the right to sublicense) to use, copy, reproduce, process, adapt, modify, publish, transmit, display, and distribute such content in any and all media or distribution methods now known or later developed.
            </p>
            
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">6.2 License Scope and Purpose</h3>
            <p className="mb-3">
              The license you grant to Scubiee is for the limited purpose of:
            </p>
            <ul className="list-disc pl-5 space-y-2">
              <li>Operating, promoting, and improving the Service</li>
              <li>Developing new programs and services</li>
              <li>Making content available to other users of the Service as per your settings</li>
              <li>Archiving or preserving content for legal, regulatory, or operational requirements</li>
            </ul>
            
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">6.3 Representations and Warranties</h3>
            <p className="mb-3">
              You represent and warrant that:
            </p>
            <ul className="list-disc pl-5 space-y-2">
              <li>You own the content you post or have the necessary licenses, rights, consents, and permissions to grant the rights herein</li>
              <li>Your content, and our use of it as permitted by these Terms, will not infringe upon or violate the rights of any third party</li>
              <li>You have obtained all required consents from any individuals whose personal information or likeness may appear in your content</li>
              <li>Your content complies with all applicable laws and regulations</li>
            </ul>
            
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">6.4 Scubiee's Intellectual Property</h3>
            <p className="mb-3">
              All rights, title, and interest in and to the Service (excluding user content), including all intellectual property rights, are and will remain the exclusive property of Scubiee and its licensors. The Service is protected by copyright, trademark, and other laws of the United States and foreign countries. Our trademarks and trade dress may not be used in connection with any product or service without our prior written consent.
            </p>
            
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">6.5 Copyright Infringement</h3>
            <p className="mb-3">
              If you believe that your copyright-protected work has been used or displayed on the Service in a way that constitutes copyright infringement, please provide us with the following information:
            </p>
            <ul className="list-disc pl-5 space-y-2">
              <li>An electronic or physical signature of the person authorized to act on behalf of the copyright owner</li>
              <li>A description of the copyrighted work that you claim has been infringed</li>
              <li>A description of where the allegedly infringing material is located on the Service</li>
              <li>Your contact information, including address, telephone number, and email</li>
              <li>A statement that you have a good faith belief that the disputed use is not authorized</li>
              <li>A statement, under penalty of perjury, that the information in your notice is accurate and that you are the copyright owner or authorized to act on their behalf</li>
            </ul>
          </div>
        </section>

        {/* Section 7: Limitation of Liability */}
        <section className="space-y-3">
          <h2 className="text-2xl font-semibold text-white border-b border-gray-700 pb-2">7. Limitation of Liability</h2>
          
          <div className="pl-4">
            <p className="mb-3">
              TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW, SCUBIEE, ITS AFFILIATES, OFFICERS, EMPLOYEES, AGENTS, PARTNERS AND LICENSORS WILL NOT BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES, INCLUDING WITHOUT LIMITATION, LOSS OF PROFITS, DATA, USE, GOODWILL, OR OTHER INTANGIBLE LOSSES, RESULTING FROM:
            </p>
            <ul className="list-disc pl-5 space-y-4">
              <li><span className="font-medium">Content Inaccuracies or Errors:</span> The use of or inability to use the Service; any content posted, transmitted, or otherwise made available through the Service, including any errors, inaccuracies, or misrepresentations in such content, whether posted by users or by Scubiee.</li>
              
              <li><span className="font-medium">Reliance on User Content:</span> Any actions taken or not taken as a result of content posted on the Service, including any decisions made or actions taken based on news, information, opinions, or other content shared by users.</li>
              
              <li><span className="font-medium">Third-Party Actions:</span> Any actions taken by third parties based on content posted to the Service, including any legal claims, business losses, reputational damage, or other consequences resulting from information published on Scubiee.</li>
              
              <li><span className="font-medium">Service Interruptions:</span> Any interruption or cessation of transmission to or from the Service; any bugs, viruses, trojan horses, or the like that may be transmitted to or through our Service by any third party.</li>
              
              <li><span className="font-medium">User Conduct:</span> Any unauthorized access to or use of our secure servers and/or any personal information stored therein; any user conduct on the Service, including defamatory, offensive, or illegal conduct of other users or third parties.</li>
              
              <li><span className="font-medium">Beta-Related Issues:</span> Any bugs, performance issues, downtime, data loss, feature changes, or other problems relating to the beta nature of the Service.</li>
            </ul>
            
            <p className="mt-4 mb-3">
              THIS LIMITATION OF LIABILITY SECTION APPLIES WHETHER THE ALLEGED LIABILITY IS BASED ON CONTRACT, TORT, NEGLIGENCE, STRICT LIABILITY, OR ANY OTHER BASIS, EVEN IF SCUBIEE HAS BEEN ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
            </p>
            
            <p className="mb-3">
              SOME JURISDICTIONS DO NOT ALLOW THE EXCLUSION OR LIMITATION OF INCIDENTAL OR CONSEQUENTIAL DAMAGES, SO THE ABOVE LIMITATIONS OR EXCLUSIONS MAY NOT APPLY TO YOU. THESE TERMS GIVE YOU SPECIFIC LEGAL RIGHTS, AND YOU MAY ALSO HAVE OTHER RIGHTS WHICH VARY BY JURISDICTION. THE DISCLAIMERS, EXCLUSIONS, AND LIMITATIONS OF LIABILITY UNDER THESE TERMS WILL NOT APPLY TO THE EXTENT PROHIBITED BY APPLICABLE LAW.
            </p>
          </div>
        </section>

        {/* Section 8: Indemnification */}
        <section className="space-y-3">
          <h2 className="text-2xl font-semibold text-white border-b border-gray-700 pb-2">8. Indemnification</h2>
          
          <div className="pl-4">
            <p className="mb-3">
              You agree to defend, indemnify, and hold harmless Scubiee, its parents, subsidiaries, affiliates, and their respective officers, directors, employees, contractors, agents, licensors, and suppliers from and against any claims, liabilities, damages, judgments, awards, losses, costs, expenses, or fees (including reasonable attorneys' fees) arising out of or relating to:
            </p>
            <ul className="list-disc pl-5 space-y-2">
              <li>Your violation of these Terms</li>
              <li>Your user content, including any claims related to defamation, privacy violations, or infringement of intellectual property or other rights</li>
              <li>Your use of the Service</li>
              <li>Your interaction with any other user of the Service</li>
              <li>Your violation of any laws, rules, regulations, codes, statutes, ordinances, or orders of any governmental or quasi-governmental authorities</li>
              <li>Any misrepresentation made by you</li>
              <li>Your violation of the rights of any third party, including any intellectual property right, publicity, confidentiality, property, or privacy right</li>
            </ul>
            
            <p className="mt-3 italic">
              We reserve the right, at your expense, to assume the exclusive defense and control of any matter for which you are required to indemnify us, and you agree to cooperate with our defense of these claims.
            </p>
          </div>
        </section>

        {/* Section 9: Modifications to Terms and Services */}
        <section className="space-y-3">
          <h2 className="text-2xl font-semibold text-white border-b border-gray-700 pb-2">9. Modifications to Terms and Services</h2>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2">9.1 Changes to Terms</h3>
            <p className="mb-3">
              We reserve the right, at our sole discretion, to modify or replace these Terms at any time. If a revision is material, we will make reasonable efforts to provide at least 15 days' notice prior to any new terms taking effect. What constitutes a material change will be determined at our sole discretion.
            </p>
            <p className="mb-3">
              By continuing to access or use our Service after any revisions become effective, you agree to be bound by the revised terms. If you do not agree to the new terms, you are no longer authorized to use the Service.
            </p>
            
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">9.2 Changes to the Service</h3>
            <p className="mb-3">
              Scubiee reserves the right at any time to:
            </p>
            <ul className="list-disc pl-5 space-y-2">
              <li>Modify, suspend, or discontinue the Service (or any part or content thereof) without notice, liability, or obligation to you</li>
              <li>Charge fees in connection with your use of the Service</li>
              <li>Offer certain features or functionalities only to certain users or at additional cost</li>
              <li>Establish general practices and limits concerning use of the Service</li>
            </ul>
            <p className="mt-3">
              These changes may be made at any time and without prior notice, particularly during the beta phase of the Service. We will not be liable to you or to any third party for any modification, suspension, or discontinuance of the Service or any part thereof.
            </p>
          </div>
        </section>

        {/* Section 10: Termination */}
        <section className="space-y-3">
          <h2 className="text-2xl font-semibold text-white border-b border-gray-700 pb-2">10. Termination</h2>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2">10.1 Termination by Scubiee</h3>
            <p className="mb-3">
              We may terminate or suspend your account and bar access to the Service immediately, without prior notice or liability, at our sole discretion, for any reason whatsoever, including but not limited to:
            </p>
            <ul className="list-disc pl-5 space-y-2">
              <li>A breach of these Terms</li>
              <li>Suspected illegal, fraudulent, or abusive activity</li>
              <li>Upon request by law enforcement or other government agencies</li>
              <li>Extended periods of inactivity</li>
              <li>System-wide service maintenance, upgrades, or other issues</li>
              <li>Unexpected technical issues or problems</li>
              <li>If we wind down the beta phase of the Service</li>
            </ul>
            
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">10.2 Termination by You</h3>
            <p className="mb-3">
              You may terminate these Terms at any time by deactivating your account and discontinuing your use of the Service. If you wish to deactivate your account, you may do so in your account settings or by contacting us directly.
            </p>
            
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">10.3 Effect of Termination</h3>
            <p className="mb-3">
              Upon termination:
            </p>
            <ul className="list-disc pl-5 space-y-2">
              <li>Your right to use the Service will immediately cease</li>
              <li>We may remove, delete, or store your content at our discretion</li>
              <li>Any licenses granted to us by you will survive termination for content already distributed</li>
              <li>All provisions of these Terms which by their nature should survive termination shall survive, including ownership provisions, warranty disclaimers, indemnity, and limitations of liability</li>
            </ul>
          </div>
        </section>

        {/* Section 11: Governing Law and Dispute Resolution */}
        <section className="space-y-3">
          <h2 className="text-2xl font-semibold text-white border-b border-gray-700 pb-2">11. Governing Law and Dispute Resolution</h2>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2">11.1 Governing Law</h3>
            <p className="mb-3">
              These Terms and your use of the Service shall be governed by and construed in accordance with the laws of the Republic of India, without regard to its conflict of law principles.
            </p>
            
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">11.2 Dispute Resolution</h3>
            <p className="mb-3">
              Any dispute arising from or relating to the subject matter of these Terms shall be finally settled by arbitration in Belagavi, Karnataka, India, using the English language in accordance with the Arbitration and Conciliation Act, 1996 then in effect, by one or more commercial arbitrators with substantial experience in resolving intellectual property and commercial contract disputes.
            </p>
            
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">11.3 Class Action Waiver</h3>
            <p className="mb-3">
              ANY DISPUTE PROCEEDINGS WILL BE CONDUCTED ONLY ON AN INDIVIDUAL BASIS AND NOT IN A CLASS OR REPRESENTATIVE ACTION OR AS A NAMED OR UNNAMED MEMBER IN A CLASS, CONSOLIDATED, REPRESENTATIVE OR PRIVATE ATTORNEY GENERAL ACTION.
            </p>
            
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">11.4 Exceptions</h3>
            <p className="mb-3">
              Notwithstanding the foregoing, Scubiee may seek injunctive or other equitable relief to protect its intellectual property rights or confidential information in any court of competent jurisdiction.
            </p>
          </div>
        </section>

        {/* Section 12: General Terms */}
        <section className="space-y-3">
          <h2 className="text-2xl font-semibold text-white border-b border-gray-700 pb-2">12. General Terms</h2>
          
          <div className="pl-4">
            <h3 className="text-xl font-medium text-blue-400 mb-2">12.1 Entire Agreement</h3>
            <p className="mb-3">
              These Terms constitute the entire agreement between you and Scubiee regarding our Service and supersede all prior agreements and understandings, whether written or oral, regarding the Service.
            </p>
            
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">12.2 Waiver and Severability</h3>
            <p className="mb-3">
              Scubiee's failure to enforce any right or provision of these Terms will not be considered a waiver of those rights. If any provision of these Terms is held to be invalid or unenforceable, that provision shall be enforced to the maximum extent possible, and the other provisions will remain in full force and effect.
            </p>
            
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">12.3 No Agency</h3>
            <p className="mb-3">
              No agency, partnership, joint venture, employee-employer, or franchiser-franchisee relationship is intended or created by these Terms.
            </p>
            
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">12.4 Assignment</h3>
            <p className="mb-3">
              You may not assign or transfer these Terms, by operation of law or otherwise, without Scubiee's prior written consent. Any attempt by you to assign or transfer these Terms without such consent will be null. Scubiee may assign or transfer these Terms, at its sole discretion, without restriction.
            </p>
            
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">12.5 Notices</h3>
            <p className="mb-3">
              Any notices or other communications provided by Scubiee under these Terms, including those regarding modifications to these Terms, will be given: (i) via email; or (ii) by posting to the Service. Notices sent via email will be effective when we send the email, and notices we provide by posting will be effective upon posting.
            </p>
            
            <h3 className="text-xl font-medium text-blue-400 mb-2 mt-4">12.6 Beta Feedback</h3>
            <p className="mb-3">
              As Scubiee is in beta, we welcome your feedback, comments, and suggestions for improvements to the Service ("Feedback"). You grant to Scubiee a non-exclusive, worldwide, perpetual, irrevocable, fully-paid, royalty-free, sublicensable and transferable license under any and all intellectual property rights that you own or control to use, copy, modify, create derivative works based upon and otherwise exploit the Feedback for any purpose.
            </p>
          </div>
        </section>

        {/* Section 13: Contact Us */}
        <section className="space-y-3">
          <h2 className="text-2xl font-semibold text-white border-b border-gray-700 pb-2">13. Contact Us</h2>
          
          <div className="pl-4">
            <p className="mb-3">
              If you have any questions about these Terms, please contact us at:
            </p>
            <p className="mb-2"><span className="font-medium">Email:</span> legal@scubiee.com</p>
            <p><span className="font-medium">Address:</span> Belagavi, Karnataka, India</p>
          </div>
        </section>
      </div>
    </div>
  );
};

export default TermsOfService;

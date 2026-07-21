import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import daily_editorial
import upload
from metadata_generation.titles import (
    polish_headline_title,
    score_title_quality,
    source_context_title,
    title_passes_publishable_bar,
)


TRUECRIME_PASSENGER_CLIP = {
    "source_title": "Cops Face Off With Dangerous Suspects - On Patrol: Live",
    "suggested_title": "Evidence Both Passenger: The Detail That Changes The Case",
    "transcript_excerpt": (
        "Both of that is going to go into evidence. What's that? "
        "The passenger's doing anything? Yeah, the front passenger is definitely "
        "getting this charge right here as well. Okay. Where was that under here? "
        "See this was on the back. This was on the floor."
    ),
    "topic_fingerprint": ["both", "passenger", "evidence", "charge", "front"],
}


class PublicCopyQualityTests(unittest.TestCase):
    def test_archive_channel_label_does_not_duplicate_brand_words(self):
        self.assertEqual(
            daily_editorial.archive_channel_label("The Joke Archive"),
            "THE JOKE ARCHIVE",
        )
        self.assertEqual(
            daily_editorial.archive_channel_label("comedy"),
            "THE COMEDY ARCHIVE",
        )

    def test_public_text_cleanup_removes_common_mojibake(self):
        broken_source_title = (
            "Cops Face Off With Dangerous Suspects "
            "\u0432\u0402\u201d On Patrol: Live"
        )
        broken_hook = (
            "That\u00e2\u20ac\u2122s why this moment "
            "\u00e2\u20ac\u201d changed the whole stop"
        )

        self.assertEqual(
            daily_editorial.clean_viewer_text(broken_source_title),
            "Cops Face Off With Dangerous Suspects - On Patrol: Live",
        )
        self.assertEqual(
            daily_editorial.clean_viewer_text(broken_hook),
            "That's why this moment - changed the whole stop",
        )
        self.assertEqual(
            upload.clean_public_text(broken_hook),
            "That's why this moment - changed the whole stop",
        )

    def test_truecrime_source_context_repairs_template_title(self):
        repaired = source_context_title(
            "truecrime",
            TRUECRIME_PASSENGER_CLIP["source_title"],
            TRUECRIME_PASSENGER_CLIP,
            TRUECRIME_PASSENGER_CLIP["topic_fingerprint"],
        )

        self.assertEqual(repaired, "Police Search Turns Into An Evidence Question")

        quality = score_title_quality(
            "truecrime",
            repaired,
            topic_terms=[
                repaired,
                TRUECRIME_PASSENGER_CLIP["source_title"],
            ],
        )

        self.assertGreaterEqual(quality.get("honesty", 0.0), 0.70)
        self.assertFalse(quality.get("generic_title"))
        self.assertFalse(quality.get("weak_template_title"))

    def test_polishes_transcript_fallback_title_casing(self):
        self.assertEqual(
            polish_headline_title("$745 and a waffle house gift card"),
            "$745 and a Waffle House Gift Card",
        )
        self.assertEqual(
            polish_headline_title("generative ai cannot follow instructions"),
            "Generative AI Cannot Follow Instructions",
        )
        self.assertEqual(
            polish_headline_title("why youtube's api matters to nba creators"),
            "Why YouTube's API Matters to NBA Creators",
        )
        self.assertEqual(
            polish_headline_title("the jonbenet jazz singer joke"),
            "The JonBenet Jazz Singer Joke",
        )

    def test_hook_generator_rejects_generic_detail_script(self):
        topic = daily_editorial.clean_headline_topic(
            "truecrime",
            TRUECRIME_PASSENGER_CLIP["suggested_title"],
            clip=TRUECRIME_PASSENGER_CLIP,
            source_title=TRUECRIME_PASSENGER_CLIP["source_title"],
            channel="On Patrol: Live",
        )
        script = daily_editorial.build_moment_hook_script(
            "truecrime",
            "This Detail",
            "standout",
            TRUECRIME_PASSENGER_CLIP,
        )

        self.assertEqual(topic, "Police Search Turns Into An Evidence Question")
        self.assertTrue(daily_editorial.public_hook_script_ok(script, topic))
        self.assertFalse(
            daily_editorial.public_hook_script_ok(
                "This detail changes how the whole story feels.",
                topic,
            )
        )

    def test_spoken_hook_topic_does_not_cut_words_mid_stem(self):
        self.assertEqual(
            daily_editorial.spoken_hook_topic("Axis Fighting Each Other in 16 Different Places"),
            "Axis Fighting Each Other in 16 Different Places",
        )
        self.assertEqual(
            daily_editorial.spoken_hook_topic("90 Days Later, MOU Says Iran Will Not Seek Nuclear Enrichment"),
            "90 Days Later, MOU Says Iran Will Not Seek Nuclear",
        )
        self.assertNotIn(
            "Different Pl stops",
            daily_editorial.build_moment_hook_script(
                "politics",
                "Axis Fighting Each Other in 16 Different Places",
                "most consequential",
            ),
        )

    def test_popular_segment_script_uses_repaired_public_title(self):
        item = {
            "source_title": "WOW! Election SHOCKER Leaves Establishment BLINDSIDED!!",
            "channel_label": "Meidas Touch",
            "clip": {
                "suggested_title": "Brad Lander Is Now the Candidate in New York District 10",
                "source_title": "WOW! Election SHOCKER Leaves Establishment BLINDSIDED!!",
                "transcript_excerpt": (
                    "Brad Lander is now the candidate in New York district 10 "
                    "because he knocked out Dan Golden."
                ),
            },
        }

        title, _topic, _terms = daily_editorial.popular_segment_public_title("politics", item)
        script = daily_editorial.build_popular_segment_script("politics", item)

        self.assertEqual(title, "Brad Lander's NYC Upset Changed the Race")
        self.assertTrue(script.startswith("Standout: "))
        self.assertIn("Brad Lander's NYC Upset", script)
        self.assertNotIn("Candidate in New York District 10", script)

    def test_countdown_intro_script_is_short_numbered_and_topic_specific(self):
        clip = {
            "source_title": "When millions of AI agents meet",
            "suggested_title": "Other People Have an Intuition That If Everybody Has an AI Advisor Helping",
            "transcript_excerpt": (
                "Other people have an intuition that if everybody has an AI advisor helping, "
                "coordination gets harder."
            ),
            "topic_fingerprint": ["ai", "advisor", "coordination"],
        }

        script = daily_editorial.build_editorial_intro(
            "technology_ai",
            "AI Advisors Make Coordination Harder",
            rank=1,
            total_count=10,
            adjective="useful",
            clip=clip,
            countdown_slot=8,
        )

        self.assertEqual(script, "Number 8: AI Advisors Make Coordination Harder.")
        self.assertLessEqual(len(script), 60)
        self.assertTrue(daily_editorial.public_hook_script_ok(script, "AI Advisors Make Coordination Harder"))

    def test_rejects_changed_the_game_word_soup_title(self):
        quality = score_title_quality(
            "sports",
            "Skiver Kick Huge Changed The Game",
            topic_terms=["skiver", "kick", "huge"],
        )

        self.assertTrue(quality.get("generic_title"))
        self.assertTrue(quality.get("mechanical_title"))
        self.assertFalse(
            title_passes_publishable_bar(
                "sports",
                "Skiver Kick Huge Changed The Game",
                topic_terms=["skiver", "kick", "huge"],
            )
        )

    def test_specific_sports_title_still_passes(self):
        quality = score_title_quality(
            "sports",
            "Cooper Flagg's Rough Debut",
            topic_terms=["cooper flagg", "rough debut"],
        )

        self.assertFalse(quality.get("generic_title"))
        self.assertGreaterEqual(quality.get("honesty", 0.0), 0.70)

    def test_rejects_cut_off_title_stems(self):
        bad_titles = [
            ("health_fitness", "Exercise Scientist Critiques Kevin Levrone's INSANE Train"),
            ("politics", "90 Days Later, MOU Says Iran Will Not Seek Nuclear Enrich"),
            ("politics", "Iran Is the Vice Chair of the UN Women's Policy Rights Co"),
        ]

        for theme, title in bad_titles:
            with self.subTest(title=title):
                quality = score_title_quality(theme, title, topic_terms=[title])
                self.assertTrue(quality.get("dangling_title"))
                self.assertTrue(quality.get("generic_title"))
                self.assertFalse(title_passes_publishable_bar(theme, title, topic_terms=[title]))

    def test_rejects_generic_locker_room_wrapper_title(self):
        quality = score_title_quality(
            "sports",
            "The Locker Room Story Around Fight Pick Choose",
            topic_terms=["fight", "pick", "choose"],
        )

        self.assertTrue(quality.get("generic_title"))
        self.assertTrue(quality.get("mechanical_title"))
        self.assertFalse(
            title_passes_publishable_bar(
                "sports",
                "The Locker Room Story Around Fight Pick Choose",
                topic_terms=["fight", "pick", "choose"],
            )
        )

    def test_rejects_generic_flashpoint_template_title(self):
        quality = score_title_quality(
            "sports",
            "Why Fight Pick Choose Became The Flashpoint",
            topic_terms=["fight", "pick", "choose"],
        )

        self.assertTrue(quality.get("generic_title"))
        self.assertTrue(quality.get("mechanical_title"))
        self.assertFalse(
            title_passes_publishable_bar(
                "sports",
                "Why Fight Pick Choose Became The Flashpoint",
                topic_terms=["fight", "pick", "choose"],
            )
        )

    def test_rejects_raw_dialogue_upload_title(self):
        quality = score_title_quality(
            "sports",
            "Just trying to figure out how to get a shot",
            topic_terms=["shot"],
        )

        self.assertTrue(quality.get("generic_title"))
        self.assertTrue(quality.get("raw_dialogue_fragment"))

    def test_rejects_more_raw_sports_sentence_titles(self):
        bad_titles = [
            "The problem is the Super Bowl really set",
            "Got up at five, went for a coffee, yeah?",
            "In fact, that's why the officiating has been called into question",
            "13 class member phenomenal player",
            "Hampton wick prick, innit?",
            "The Sports Debate That Split The Room",
            "Audrey, who's the better racer?",
            "Playoff football or World Cup soccer?",
            "Super Bowl or when the US Women's National team got the World Cup?",
        ]

        for title in bad_titles:
            with self.subTest(title=title):
                quality = score_title_quality("sports", title, topic_terms=["sports"])
                self.assertTrue(quality.get("generic_title"))
                self.assertFalse(title_passes_publishable_bar("sports", title, topic_terms=["sports"]))

    def test_rejects_raw_comedy_question_and_asr_titles(self):
        bad_titles = [
            "Kennedy Jr., the Secretary of Health and Human Services",
            "Which one was to pay the bills?",
            "Anyway, there's some crazy S-fals happening",
            "Who released this new report that set a quarter million people?",
            "The reality was made illegal in 2006 in the state of Washington",
            "A weird movie question?",
            "What is the real life that isn't connected to the autism?",
            "Petersburg either Oh, yeah, Ampeter's work Florida?",
            "Who woulda thought, bro, honestly?",
            "When was Dawson's Creek when that come out?",
            "What's the back story behind the word play in title there?",
            "Dude, is that funny?",
            "What's the mile high city?",
            "Alright cool, everybody's 10 setup",
            "All right cool Alright cool, everybody's 10 setup",
        ]

        for title in bad_titles:
            with self.subTest(title=title):
                quality = score_title_quality("comedy", title, topic_terms=["comedy"])
                self.assertTrue(quality.get("generic_title"))
                self.assertTrue(quality.get("raw_dialogue_fragment"))
                self.assertFalse(title_passes_publishable_bar("comedy", title, topic_terms=["comedy"]))

    def test_rejects_thin_comedy_label_titles(self):
        bad_titles = [
            "Magnus Carlsen Rivalry",
            "Magnus Carlsen Story",
            "The Italy Childhood Story",
        ]

        for title in bad_titles:
            with self.subTest(title=title):
                quality = score_title_quality("comedy", title, topic_terms=[title])
                self.assertTrue(quality.get("generic_title"))
                self.assertFalse(title_passes_publishable_bar("comedy", title, topic_terms=[title]))

    def test_rejects_gaming_question_and_subtitle_fragments(self):
        bad_titles = [
            "New skates too or extra skates?",
            "Who's that player for 200?",
            "Team Baguette comes back and wins the game",
            "Number 10, Guilds full regeneration, Street Fighter 3",
            "What's the simplest puff of these resistance from point A to point B?",
            "Lairy goes looking for love in several wrong places",
            "Shane says, that wasn't a threat",
            "Echo Chrome was 2008, apparently",
            "Let's learn some French, 150",
            "Go to shop of Vi.com slash fear",
            "AI type thing because if people don't know Thick people literally like more",
            "Whoever the coach or fanatic is there or whoever the players are fanatic are",
            "The console market is not like that though right now",
            "Yep, Team Cressant gets the guess first",
            "Brutal Legend was October of 2009",
            "PlayStation six would cost Sony to put together right now",
            "Toy Story 4 is a beautiful movement",
            "Instead of the build materials for the PS6 was $760",
            "Sinna, Poke Man, Love or Host, hypocrite",
            "10 million units of the very enthusiast base",
            "The Bediene Chronicles time-bending Mortal Kombat 11",
            "Cuties like oh shit, there's so many people in this car",
        ]

        for title in bad_titles:
            with self.subTest(title=title):
                quality = score_title_quality("gaming", title, topic_terms=[title])
                self.assertTrue(quality.get("generic_title"))
                self.assertFalse(title_passes_publishable_bar("gaming", title, topic_terms=[title]))

    def test_rejects_generic_finance_investor_template_title(self):
        bad_titles = [
            "Why Embarrassing Errors Words Still Matters To Investors",
            "Why Wealth Jobs Destroy Still Matters To Investors",
            "Why SpaceX IPO Matters To Investors",
        ]

        for title in bad_titles:
            with self.subTest(title=title):
                quality = score_title_quality("finance", title, topic_terms=["finance"])
                self.assertTrue(quality.get("generic_title"))
                self.assertTrue(quality.get("mechanical_title"))
                self.assertFalse(title_passes_publishable_bar("finance", title, topic_terms=["finance"]))

    def test_rejects_raw_technology_ai_transcript_titles(self):
        bad_titles = [
            "Around 30% to 30% of a Lab's Compute Goes to Inference",
            "RL Is Great at Concentrating the Update to Only What Is Relevant to Getting the Outcome",
            "Which Is What Agents Have",
            "The Labs Plans for This Latter Category of Jobs Is First to Automate AI",
            "The AI Just Has to Re-Implement Them Without Internet Access",
            "What Is the Oral Environment to Make an AI That Is as Good at Politics As",
            "The Phenomenon of Why See Founders Getting Younger and Younger",
            "Once More, That's Clod.ai Slash TCR",
            "Managing a Team of Agencies Different Compared to Managing a Team of Humans",
            "5.5 into Doing a Series of Experiments That Can Run for Weeks for Months",
            "Which Is Like, the Model Layer Is Changing Still",
            "Given the Model Evaluation Cycle",
            "First Is Truth and Justice Is the Immune System for Society",
        ]

        for title in bad_titles:
            with self.subTest(title=title):
                quality = score_title_quality("technology_ai", title, topic_terms=["ai", "model"])
                self.assertTrue(quality.get("raw_dialogue_fragment") or quality.get("generic_title"))
                self.assertFalse(title_passes_publishable_bar("technology_ai", title, topic_terms=["ai", "model"]))

    def test_technology_ai_transcript_topics_rescue_good_clips_from_raw_titles(self):
        clips = [
            (
                {
                    "source_title": "AI:AM #4: Cameron on Model Consciousness",
                    "suggested_title": "Other People Have an Intuition That If Everybody Has an AI Advisor Helping",
                    "transcript_excerpt": (
                        "Other people have an intuition that if everybody has an AI advisor helping, "
                        "then coordination gets harder and the government may need to step in."
                    ),
                    "topic_fingerprint": ["growth", "will", "economic", "fine", "intuition", "helping", "solve", "coordination"],
                },
                "AI Advisors Make Coordination Harder",
            ),
            (
                {
                    "source_title": "Zynga Founder: Consumer Is Not Investible Right Now",
                    "suggested_title": "How Do We Stay Passionate About the Instinct That We're Pursuing",
                    "transcript_excerpt": (
                        "How do we stay passionate about the instinct that we're pursuing, the vision, "
                        "but dispassionate about this particular product variant and idea?"
                    ),
                    "topic_fingerprint": ["product", "night", "monday", "vision", "variant", "instinct"],
                },
                "Product Vision Versus Product Variants",
            ),
        ]

        for clip, expected in clips:
            with self.subTest(expected=expected):
                topic = daily_editorial.topic_label_from_clip(clip, theme="technology_ai")

                self.assertEqual(topic, expected)
                self.assertTrue(daily_editorial.topic_supported_by_clip(topic, clip))
                self.assertTrue(
                    daily_editorial.public_editorial_topic_ok(
                        "technology_ai",
                        topic,
                        topic_terms=daily_editorial.clip_topic_terms(clip, limit=10),
                        allow_short_topic=False,
                    )
                )

    def test_social_title_prefers_clean_topic_over_raw_suggested_title(self):
        clip = {
            "source_title": "AI:AM #4: Cameron on Model Consciousness",
            "suggested_title": "Other People Have an Intuition That If Everybody Has an AI Advisor Helping",
            "transcript_excerpt": (
                "Other people have an intuition that if everybody has an AI advisor helping, "
                "then coordination gets harder and the government may need to step in."
            ),
            "topic_fingerprint": ["coordination", "ai advisor"],
        }

        title = daily_editorial.sanitize_social_title(
            "technology_ai",
            "Needs Specific Editorial Title",
            "AI Advisors Make Coordination Harder",
            clip=clip,
            source_title=clip["source_title"],
            content_format="countdown",
        )

        self.assertEqual(title, "AI Advisors Make Coordination Harder")

    def test_rejects_raw_health_transcript_titles(self):
        bad_titles = [
            "Why Is Having a Sharing Mindset So Important?",
            "Why Not Just Make the Walk a Little Bit Longer",
            "17-Year-Old Girls Come to Me Showing Me Text Messages",
            "The Trap Is Opening Up So Much Optionality Without the Concordant",
            "The So-Called Generous Offer at Camp David in July 2000 by Hoen Barak to Arifat",
            "Someone Huge Like Kevin Lebronie Says, 68 Reps Are Better",
            "The Only Real Challenge That Might Come Up During That 3 Hour Window Is Feeling Incredibly",
            "The Reality of Why the Hundred-Pound Dumbbell Curl Is a Thing That Correlates to Kevin",
            "The Eight Sleep Pod Five Comes with a Smart Cover",
            "Body Fasting Changes: the Health Detail to Rethink",
            "Health Changed View: the Health Detail to Rethink",
            "How Can Parents Like Protect Their Kids from Everything Coming at Them?",
        ]

        for title in bad_titles:
            with self.subTest(title=title):
                quality = score_title_quality("health_fitness", title, topic_terms=["health", "body"])
                self.assertTrue(
                    quality.get("raw_dialogue_fragment")
                    or quality.get("generic_title")
                    or quality.get("mechanical_title")
                )
                self.assertFalse(title_passes_publishable_bar("health_fitness", title, topic_terms=["health", "body"]))

    def test_rejects_raw_politics_transcript_titles(self):
        bad_titles = [
            "Map Please, There Are 50 over 50 Muslim Nations",
            "How in the World Would the United States Need Israel More Than Israel Needs the United",
            "250 Foot Monuments That the People Who Voted for Him to Lower Their Grocery Bills Are",
            "Trump Breaks Day One Promise to Lower Costs as Prices Surge Across America in First Six",
            "Why Was This Effective in Actually Getting a Respon",
            "Here's, This Is a Problem of the Legacy of Operation Boot",
            "Now That's Also a Problem Sometimes for Solar",
            "York Election Was a Wake Up Call",
            "Public Utilities in Denmark in February 22 in February 22",
            "450,000 Kids That Were Given to Sponsors That Weren't Vetted",
            "What the Supreme Court Said Is an Individual Doesn't Arrive in the United States",
            "The Separations Resulting from the Admins' Zero Tolerance Policy",
            "50,000 Minus the Number of Combatants That the Idea Have Set",
            "Biohacker Brian Johnson Recently Boasted About His Girlfriend's Top 1% Vagina",
            "Let Me Go Back to the Market Reasons of the World",
            "Winemoms Love True Crime Podcasts",
            "The Policy Fight That Needs Context",
            "Growth May Not Be Booming",
            "Maybe America Needs Another 9-11",
        ]

        for title in bad_titles:
            with self.subTest(title=title):
                quality = score_title_quality("politics", title, topic_terms=["policy", "election"])
                self.assertTrue(
                    quality.get("raw_dialogue_fragment")
                    or quality.get("generic_title")
                    or quality.get("overlong_title")
                    or quality.get("dangling_title")
                    or quality.get("asr_sentence_title")
                )
                self.assertFalse(title_passes_publishable_bar("politics", title, topic_terms=["policy", "election"]))

    def test_specific_politics_titles_still_pass(self):
        good_titles = [
            "AI Spending Becomes a Policy Fight",
            "The MAGA Supreme Court's Assault on America",
            "Denmark Now Home to Just over 6 Million People",
        ]

        for title in good_titles:
            with self.subTest(title=title):
                quality = score_title_quality("politics", title, topic_terms=["policy", "election"])
                self.assertFalse(quality.get("generic_title"))
                self.assertFalse(quality.get("asr_sentence_title"))
                self.assertGreaterEqual(quality.get("honesty", 0.0), 0.70)

    def test_rejects_raw_finance_sentence_titles(self):
        bad_titles = [
            "A lot of American wealth is wrapped up in them",
            "20% of devs salaries goes toans",
            "Now, let's move up talking about $100,000 a year",
            "Now what not is the US equivalent of live shopping worth $10 billion",
            "Let me just pull up a chart of Bitcoin here",
            "The reality is that running an investment firm will always require governments",
            "The technical problem is that large language models",
            "What the embarrassing errors revealed is the systems are not really reasoning",
            "What's six myths in this, um, little envelope here?",
            "How does that shape the perspective now being the boss",
            "000 just to make sure something doesn't pop up",
            "100% and lastly biological stresses",
            "500 a month going towards groceries",
            "20 year olds that drive the market that offered themselves military service",
            "Progression at Amazon is not exactly a straight lie",
            "Turning the market into something that's parabolic",
            "Investors are turning to private markets to find new sources of return to stability",
            "Emily has really one of the most fascinating jobs in the world of investing",
            "Stocks 2.0 is designed around deeper liquidity",
            "The rent-to-price ratio is not terrible",
            "How Disinflationary Core Close Changes The Math",
            "Chip AI Changed",
            "Indie Lee spent 18 years managing multi-billion dollar endowment funds in New York",
            "55% of homes right now are selling above list price still",
            "Man, money starts now",
            "How do you build that Fortress balance sheet through two main engi",
            "How does benchmark come into the fray?",
            "260 to $300 a night, which is pretty awesome",
            "Gen Z about wasting money on crypto",
            "Now let's go to $150,000 of annual income",
            "500 of post-tax or Roth investments",
            "One belief is AI is done with them",
            "Canada has banned 550, and the US has banned 12",
            "China already has 250% more electricity than America",
            "Mark Carnier had already agreed to allow in about 40",
            "Folks have been comparing this to the 2015 Iran nuclear deal",
            "Why would an intelligent investor or an intelligent seller ever sell for cash?",
            "The conflict has already cost 13 American lives",
            "Sweden has gone from two years to six years in the last 70 years",
            "The problem has always been the same as basically impossible for regular",
            "China typically has somewhere between 70 to 95% market share",
            "$100 billion or whatever the numbers aren't public",
            "97 to 98% of women don't have the hormonal environment to bulk",
            "Mortgage is a debt",
            "The gigette is officially launching the stock 2.0 era",
            "The Mondami suite chances were just 26 before Election Day",
            "How do these stupid bubbles happen over and over again?",
            "Before investing carefully, consider the investment objective",
            "Stocksfall 30% in a week.com bubble right before bus",
            "When AI is coming out with Slop, et cetera",
        ]

        for title in bad_titles:
            with self.subTest(title=title):
                quality = score_title_quality("finance", title, topic_terms=["finance"])
                self.assertTrue(quality.get("generic_title"))
                self.assertFalse(title_passes_publishable_bar("finance", title, topic_terms=["finance"]))

    def test_upload_ready_packages_do_not_reuse_public_titles(self):
        packages = [
            {
                "theme": "technology_ai",
                "title": "AI Advisors Make Coordination Harder",
                "source_title": "When millions of AI agents meet",
                "source_channel": "Tech Podcast",
                "content_signal": {"topic": "AI Advisors Make Coordination Harder"},
                "platforms": {"youtube_shorts": {"title": "AI Advisors Make Coordination Harder"}},
                "rank_signals": {},
                "tags": ["ai", "agents"],
                "transcript_excerpt": "AI advisors make coordination harder when everyone optimizes with a different agent.",
            },
            {
                "theme": "technology_ai",
                "title": "AI Advisors Make Coordination Harder",
                "source_title": "OpenAI Codex lead on the new shape of product work",
                "source_channel": "Builder Podcast",
                "content_signal": {"topic": "Product Vision Beats Feature Variants"},
                "platforms": {"youtube_shorts": {"title": "AI Advisors Make Coordination Harder"}},
                "rank_signals": {},
                "tags": ["product", "ai"],
                "transcript_excerpt": "Product vision matters more than shipping a dozen disconnected feature variants.",
            },
        ]

        daily_editorial.enforce_unique_package_titles("technology_ai", packages, {})
        titles = [
            (package.get("platforms") or {}).get("youtube_shorts", {}).get("title")
            for package in packages
        ]

        self.assertEqual(len(set(titles)), 2)
        self.assertIn("Product Vision Beats Feature Variants", titles)


if __name__ == "__main__":
    unittest.main()

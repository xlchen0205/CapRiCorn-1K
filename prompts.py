SUBJECT_EVENT_TEMPLATE = """You will be given a video caption and a specific event involving one or more subjects (predefined and enclosed in <>; do NOT add any subjects that you think should be included). Your task is to determine how this event is represented in the caption by assigning it to one of the following categories:
- "correctly mentioned": the event is accurately described in the caption, possibly with only minor omissions or negligible errors.
- "mentioned but with errors": the event is mentioned in the caption, but contains substantial inaccuracies, distortions, or misleading details.
- "not mentioned": the event is not described in the caption at all.

If the classification is "correctly mentioned" or "mentioned but with errors":
- From the **local caption segment** at the moment the event occurs, identify the subject ID enclosed in <> within the event, and extract the corresponding subject description from the **local caption segment**. Only when the local subject description is overly vague (e.g., “his”, “her”, “their”, “it”, “the man”) is it allowed to use the global context to obtain a more specific subject description.
- The extracted content must be strictly from the local descriptions present in the caption text, NOT copied or inferred from the provided subject description in the event.
- Each subject’s local description should be concise while still containing enough identifying information.

If the classification is "not mentioned":
- Set the subject description value to null.


Video caption:
{}

Event:
{}

Subject ID list:
{}

Output format:
```json
{{
    "event_type": "xx",  // One of ["correctly mentioned", "mentioned but with errors", "not mentioned"]
    "reason": "xx",  // Brief justification for event_type; no double quotes inside
    "subject_description_in_caption": {{
        "<sbj_id_1>": xx,
        "<sbj_id_2>": xx, // if exists
        ...
    }}  // **Brief subject descriptions dict (rather than event description)** summarized from caption or null (only when the event_type is "not mentioned"). **Do not use any pronouns (e.g., his, her, their, it)**; instead, replace them with their corresponding referents identified from the caption.
}}
```
""".strip()


OTHER_EVENT_TEMPLATE = """You will be given a video caption and a specific event. Your task is to determine how this event is represented in the caption by assigning it to one of the following categories:
- "correctly mentioned": the event is accurately described in the caption, possibly with only minor omissions or negligible errors.
- "mentioned but with errors": the event is mentioned in the caption, but contains substantial inaccuracies, distortions, or misleading details.
- "not mentioned": the event is not described in the caption at all.

Video caption:
{}

Event:
{}


Output format:
```json
{{
    "event_type": "xx",  // One of ["correctly mentioned", "mentioned but with errors", "not mentioned"]
    "reason": "xx",  // Brief justification for event_type; no double quotes inside
}}
```
""".strip()


CATEGORIZE_TEMPLATE = """You will be given a list of subject descriptions and a video caption. Your task is to group these descriptions into clusters, where each cluster contains descriptions that refer to the same real-world subject, based on both the descriptions and the caption context.

Descriptions should be grouped together only if they satisfy at least **one of** the following conditions:
1. They share sufficiently specific matching **appearance attributes**, without considering actions.
2. They contain the same subject name. In this case, attribute differences must be ignored, and **all descriptions with the same subject name must always be grouped into a single cluster**.
3. Based on the video caption, it can be reasonably and clearly inferred that the descriptions refer to the same subject.

Guidelines:

- Note that identical descriptions do not necessarily refer to the same subject.
    - For example, multiple generic references such as “a girl” should be treated as distinct subjects, because the only feature "girl" is too vague to determine that they refer to the same entity, unless the caption clearly implies they refer to the same entity (e.g., there is only one girl in the caption).
    - Similarly, ambiguous descriptions like "one of xxx" or "two other xxx", which lack distinguishing details, should be treated as referring to different subjects (i.e., if the phrase "one of xxx" appears four times, it should be classified as four **distinct** categories), unless the caption provides sufficient evidence to identify them as the same entity.

- Conversely, non-identical descriptions may still refer to the same subject, as long as they convey consistently matching attributes, share identical subject names, or can be reasonably and clearly inferred from the caption.
    - For example, descriptions with similar attributes such as “a boy with a light-grey shirt” and “the boy in a grey shirt” should be grouped into the same category.
    - Similarly, descriptions that include the same subject name, such as “James”, “James in a white shirt” and “James, dressed in a dark suit jacket”, should also be grouped into one cluster, even if their outfits differ, because they contain the same subject name.

- Ensure that every subject description is assigned to exactly one cluster.


List of subject descriptions:
{}

Video Caption:
{}

Output format:
```json
{{
    "category_1": ["original subject description 1", "original subject description 2", ...],
    "category_2": ["original subject description 3"], // optional
    ...
}}
```
""".strip()

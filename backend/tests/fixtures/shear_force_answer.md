## Overview
**Shear force** is the internal force that acts parallel to a beam's cross-section and keeps one side of a cut from sliding past the other. It is covered in Lecture 7, *Shear Force and Bending Moment Diagrams*, and it is the first step toward finding bending stresses [Lecture_07_Shear_and_Moment.pdf].

## Key concepts
### Internal shear force
Cut the beam at a section \(x\) and draw a free-body diagram of either side. Vertical equilibrium of that piece gives the internal shear force \(V(x)\):
\[
V(x) = \sum F_{y,\text{left}}
\]
This is the quantity a shear force diagram plots along the beam [Lecture_07_Shear_and_Moment.pdf]. Engineers size bridge girders' webs from the peak of this diagram (online).

### Sign convention
Positive shear acts **downward on the right face** and **upward on the left face** of a cut, so it tends to rotate the segment clockwise. Keep this convention fixed for the whole problem, or the diagram will flip sign partway [Lecture_07_Shear_and_Moment.pdf].

### Load, shear and moment relations
A distributed load \(w(x)\) changes the shear, and the shear changes the moment:
\[
\frac{dV}{dx} = -w(x), \qquad \frac{dM}{dx} = V(x)
\]
So the area under the load curve is the change in shear, and the area under the shear diagram is the change in moment [Lecture_07_Shear_and_Moment.pdf].

### Point loads and jumps
A concentrated force \(P\) makes the shear diagram jump by \(P\) at that point. The moment diagram changes slope there but does not jump [Tutorial_04_Beams.pdf].

## Worked example
Simply supported beam, span \(L = 4\ \text{m}\), point load \(P = 10\ \text{kN}\) at midspan [Tutorial_04_Beams.pdf]:
1. By symmetry the reactions are \(R_A = R_B = 5\ \text{kN}\).
2. For \(0 < x < 2\ \text{m}\): \(V = +5\ \text{kN}\).
3. At \(x = 2\ \text{m}\) the shear jumps down by 10 kN.
4. For \(2 < x < 4\ \text{m}\): \(V = -5\ \text{kN}\).
5. The moment peaks where \(V\) changes sign: \(M_{\max} = 5 \times 2 = 10\ \text{kN}\cdot\text{m}\).

## Common mistakes
- Mixing sign conventions between the left and right free-body diagrams.
- Forgetting the jump in \(V\) under a point load.
- Treating shear force (a force, in kN) as shear stress (a force per area, in MPa).

## Check yourself
1. Where along a beam does the bending moment reach its maximum?
<details><summary>Answer</summary>

Where the shear force crosses zero, because \(dM/dx = V\) [Lecture_07_Shear_and_Moment.pdf].

</details>

2. A uniform load \(w\) acts on a span. What shape is the shear diagram there?
<details><summary>Answer</summary>

A straight line with slope \(-w\), since \(dV/dx = -w\).

</details>

3. Why does a point load cause a jump in \(V\) but not in \(M\)?
<details><summary>Answer</summary>

The force acts over zero length, so it changes shear instantly while the moment, the integral of shear, stays continuous.

</details>

## Study checklist
1. Practise cutting a beam and writing \(V(x)\) from equilibrium today.
2. Memorise \(dV/dx = -w\) and \(dM/dx = V\).
3. Redo Tutorial 4, problems 1 to 3, tomorrow without notes.
4. Revisit cantilever diagrams next week before the midterm.
